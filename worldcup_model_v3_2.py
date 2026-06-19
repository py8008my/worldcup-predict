#!/usr/bin/env python3
"""
世界杯冷门预测模型 v3.2
======================
数据源：体彩官方API(webapi.sporttery.cn) + 本地知识库(knowledge_base.json)
玩法覆盖：胜平负 / 让球胜平负 / 总进球 / 比分 / 半全场 / 混合过关
v3.2新增：比分信号增强(胜/负其他+冷门比分) + 冷门类型细分(Type1/2/3) + 知识库深度利用(攻防差值+战意) + 双方案(激进+稳健)
"""

import json
import urllib.request
import ssl
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional

KB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base.json")

SUPER_FAVORITE = 1.30
FAVORITE = 1.50
MODERATE = 1.80

# 冷门类型
COLD_TYPE1 = 'Type1-超级冷门'  # 超级热门(赔率<1.30)被逼平或输球
COLD_TYPE2 = 'Type2-中等冷门'  # 中强队(赔率1.30-1.80)被弱队爆冷
COLD_TYPE3 = 'Type3-进球冷门'  # 预期高进球比赛打出0-1球

# CRS特殊key映射
CRS_SPECIAL = {'s1sa': '胜其他', 's1sd': '平其他', 's1sh': '负其他',
               's5sa': '胜其他', 's5sd': '平其他', 's5sh': '负其他'}

# ═══════════════════════════════════════════
# 0. 知识库
# ═══════════════════════════════════════════

def load_knowledge_base() -> dict:
    if os.path.exists(KB_FILE):
        try:
            with open(KB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return default_kb()

def default_kb():
    return {
        "matches": [
            {"date":"2026-06-12","match":"卡塔尔vs瑞士","score":"1:1","goals":2,"had":"平"},
            {"date":"2026-06-12","match":"巴西vs摩洛哥","score":"1:1","goals":2,"had":"平"},
            {"date":"2026-06-12","match":"海地vs苏格兰","score":"0:1","goals":1,"had":"客胜"},
            {"date":"2026-06-13","match":"德国vs库拉索","score":"7:1","goals":8,"had":"主胜"},
            {"date":"2026-06-13","match":"荷兰vs日本","score":"2:2","goals":4,"had":"平"},
            {"date":"2026-06-13","match":"科特迪瓦vs厄瓜多尔","score":"1:0","goals":1,"had":"主胜"},
            {"date":"2026-06-13","match":"瑞典vs突尼斯","score":"5:1","goals":6,"had":"主胜"},
            {"date":"2026-06-14","match":"西班牙vs佛得角","score":"0:0","goals":0,"had":"平","note":"超级冷门"},
            {"date":"2026-06-14","match":"比利时vs埃及","score":"1:1","goals":2,"had":"平"},
            {"date":"2026-06-14","match":"沙特vs乌拉圭","score":"1:1","goals":2,"had":"平"},
            {"date":"2026-06-14","match":"伊朗vs新西兰","score":"2:2","goals":4,"had":"平"},
        ],
        "teams": {},
        "patterns": {"super_draw": 4, "super_win": 1, "total_cold": 8, "updated": "2026-06-15"},
        "odds_snapshots": {}
    }

def save_kb(kb):
    with open(KB_FILE, 'w', encoding='utf-8') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

def fuzzy_team(name, kb):
    """模糊匹配队名，返回含攻防指标的球队信息"""
    teams = kb.get('teams', {})
    if name in teams:
        info = teams[name]
    else:
        for tn in teams:
            if tn.startswith(name) or name.startswith(tn):
                info = teams[tn]
                break
        else:
            return {}
    # 注入攻防指标
    info_with_strength = dict(info)
    info_with_strength.update(calc_team_strength(info))
    return info_with_strength

def calc_team_strength(team_info):
    """计算球队攻防强度指标"""
    games = team_info.get('wins', 0) + team_info.get('draws', 0) + team_info.get('losses', 0)
    if games == 0:
        return {}
    gf_avg = team_info.get('gf', 0) / games
    ga_avg = team_info.get('ga', 0) / games
    diff = gf_avg - ga_avg
    return {
        'gf_avg': round(gf_avg, 2),   # 场均进球
        'ga_avg': round(ga_avg, 2),   # 场均失球
        'gd_avg': round(diff, 2),      # 场均净胜球(攻防差值)
        'attack_rating': '强' if gf_avg >= 2.0 else ('中' if gf_avg >= 1.0 else '弱'),
        'defense_rating': '强' if ga_avg <= 0.8 else ('中' if ga_avg <= 1.5 else '弱'),
    }

def calc_motivation(team_name, kb):
    """
    根据小组形势判断战意等级
    返回: 'must_win'(必须赢) / 'can_draw'(可以平) / 'relaxed'(无所谓)
    """
    groups = kb.get('groups', {})
    for group_name, group_data in groups.items():
        standings = group_data.get('standings', {})
        if team_name not in standings:
            continue
        team_standing = standings[team_name]
        pts = team_standing.get('pts', 0)
        played = team_standing.get('played', 0)
        total_games = 3  # 小组赛共3场
        remaining = total_games - played
        
        if remaining == 0:
            return 'relaxed'
        
        all_pts = sorted([s.get('pts', 0) for s in standings.values()], reverse=True)
        
        if pts == 0 and remaining == 1:
            return 'must_win'
        elif pts <= 1 and remaining == 1:
            return 'must_win'
        elif pts >= 6:
            return 'relaxed'
        elif pts >= 4 and remaining == 1:
            return 'can_draw'
        else:
            return 'must_win'
    return 'can_draw'  # 不在小组数据中，默认

# ═══════════════════════════════════════════
# 1. 数据获取
# ═══════════════════════════════════════════

def fetch_sporttery():
    url = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?poolCode=had,hhad,crs,hafu,ttg&channel=c"
    hdrs = {"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15","Referer":"https://m.sporttery.cn/"}
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))

def fetch_results():
    """从fifawatch.com抓取世界杯赛果，回写知识库"""
    results = []
    try:
        url = "https://fifawatch.com/zh/"
        hdrs = {"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)","Accept-Language":"zh-CN,zh;q=0.9"}
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            html = r.read().decode('utf-8')
        import re
        # 从页面中提取 "最终比分" 区域: 球队名 比分 球队名
        # 匹配模式: 中文队名 + 空格 + 数字:数字 + 空格 + 中文队名
        pattern = r'([\u4e00-\u9fa5]{2,6})\s+(\d+)\s*:\s*(\d+)\s+([\u4e00-\u9fa5]{2,6})'
        seen = set()
        for m in re.finditer(pattern, html):
            home = m.group(1); hg = int(m.group(2)); ag = int(m.group(3)); away = m.group(4)
            key = (home, away)
            if key in seen: continue
            seen.add(key)
            total = hg + ag
            had = '主胜' if hg>ag else ('平' if hg==ag else '客胜')
            results.append({
                'date': datetime.now().strftime('%Y-%m-%d'),
                'match': f"{home}vs{away}",
                'score': f"{hg}:{ag}",
                'goals': total,
                'had': had
            })
    except Exception as e:
        pass  # 静默跳过
    return results

def update_kb_results(kb, new_results):
    """将新赛果合并到知识库，去重"""
    existing = kb.get('matches', [])
    existing_keys = {(m['date'], m['match']) for m in existing}
    added = 0
    for r in new_results:
        key = (r['date'], r['match'])
        if key not in existing_keys:
            existing.append(r); existing_keys.add(key); added += 1
    if added > 0:
        kb['matches'] = existing
        _update_patterns(kb)
        print(f"📊 赛果回写:{added}场新结果")
    return added

def _update_patterns(kb):
    """根据知识库matches重新计算patterns"""
    matches = kb.get('matches', [])
    kb['patterns']['super_draw'] = sum(1 for m in matches if m.get('had') == '平')
    kb['patterns']['total_cold'] = sum(1 for m in matches if m.get('had') in ('平', '客胜'))

def parse_matches(raw):
    ms = []
    for day in raw.get('value',{}).get('matchInfoList',[]):
        for m in day.get('subMatchList',[]):
            mt = {
                'match_id':m.get('matchId'),'match_num':m.get('matchNum'),
                'match_num_str':m.get('matchNumStr',''),'home':m.get('homeTeamAbbName',''),
                'away':m.get('awayTeamAbbName',''),'home_code':m.get('homeTeamCode',''),
                'away_code':m.get('awayTeamCode',''),'league':m.get('leagueAbbName',''),
                'match_date':m.get('matchDate',''),'match_time':m.get('matchTime',''),
                'status':m.get('matchStatus',''),'is_hot':m.get('isHot',0),
            }
            # had
            had=m.get('had',{})
            if had:
                mt['had_h']=float(had.get('h',0)) if had.get('h') not in(None,'') else None
                mt['had_d']=float(had.get('d',0)) if had.get('d') not in(None,'') else None
                mt['had_a']=float(had.get('a',0)) if had.get('a') not in(None,'') else None
                mt['had_upd']=f"{had.get('updateDate','')} {had.get('updateTime','')}"
            # hhad
            hhad=m.get('hhad',{})
            if hhad:
                mt['hhad_line']=hhad.get('goalLine','')
                mt['hhad_h']=float(hhad.get('h',0)) if hhad.get('h') not in(None,'') else None
                mt['hhad_d']=float(hhad.get('d',0)) if hhad.get('d') not in(None,'') else None
                mt['hhad_a']=float(hhad.get('a',0)) if hhad.get('a') not in(None,'') else None
                mt['hhad_upd']=f"{hhad.get('updateDate','')} {hhad.get('updateTime','')}"
            # crs
            crs=m.get('crs',{})
            if crs:
                mt['crs']={}
                for k in crs:
                    # 胜其他/负其他（排除平其他）
                    if k in CRS_SPECIAL:
                        if '平其他' not in CRS_SPECIAL[k]:
                            mt['crs'][CRS_SPECIAL[k]]=float(crs[k]) if crs[k] not in(None,'') else 0
                    elif k.startswith('s') and not k.endswith('f') and k[1:].replace('s','').isdigit():
                        try:
                            parts=k[1:].split('s')
                            h=int(parts[0]); a=int(parts[1])
                            mt['crs'][f"{h}:{a}"]=float(crs[k]) if crs[k] not in(None,'') else 0
                        except:pass
                mt['crs_upd']=f"{crs.get('updateDate','')} {crs.get('updateTime','')}"
            # ttg
            ttg=m.get('ttg',{})
            if ttg:
                mt['ttg']={}
                for k in ttg:
                    if k.startswith('s') and not k.endswith('f'):
                        try: mt['ttg'][int(k[1:])]=float(ttg[k]) if ttg[k] not in(None,'') else 0
                        except:pass
                mt['ttg_upd']=f"{ttg.get('updateDate','')} {ttg.get('updateTime','')}"
            # hafu
            hafu=m.get('hafu',{})
            if hafu:
                mt['hafu']={}
                for code,label in [('hh','胜胜'),('hd','胜平'),('ha','胜负'),('dh','平胜'),('dd','平平'),('da','平负'),('ah','负胜'),('ad','负平'),('aa','负负')]:
                    if code in hafu and hafu[code] not in(None,''): 
                        try:mt['hafu'][label]=float(hafu[code])
                        except:pass
                mt['hafu_upd']=f"{hafu.get('updateDate','')} {hafu.get('updateTime','')}"
            ms.append(mt)
    return ms

# ═══════════════════════════════════════════
# 2. 信号检测 (v3: +kb)
# ═══════════════════════════════════════════

def sig_had(m, kb):
    h=m.get('had_h');d=m.get('had_d');a=m.get('had_a')
    if not h:
        if m.get('hhad_line')=='+2':h,d,a=13.0,7.0,1.21
        else:return{'score':0,'signals':[],'recs':[]}
    score=0;sigs=[];recs=[]
    if h<SUPER_FAVORITE and d and d<5.0:
        score+=35;sigs.append(f"超级热门({h})平赔仅{d}→防平[Type1]")
    if h<FAVORITE and a and a<7.0:
        score+=25;sigs.append(f"客胜赔率仅{a}→冷门空间[Type2]")
    if h and d and a:
        mg=1/h+1/d+1/a
        if mg>1.12:score+=15;sigs.append(f"利润率{mg:.2f}→不确定性")
        # 赔率对比（公平赔率vs体彩）
        fair_h=1/(1/h/mg)
        dev=(h-fair_h)/fair_h*100
        if abs(dev)>10:sigs.append(f"体彩vs公平偏离{dev:.0f}%")
    # 知识库
    pat=kb.get('patterns',{})
    if h<SUPER_FAVORITE and pat.get('super_draw',0)>=2:
        score+=20;sigs.append(f"知识库:超级强队{pat['super_draw']}场被逼平")
    # 攻防差值
    tf_h=fuzzy_team(m.get('home',''),kb)
    tf_a=fuzzy_team(m.get('away',''),kb)
    sh=calc_team_strength(tf_h);sa=calc_team_strength(tf_a)
    if sh.get('defense_rating')=='弱' and a and a<8.0:
        score+=10;sigs.append(f"主队防守弱(场均失{sh.get('ga_avg','?')})→客队进球可能")
    if sa.get('attack_rating')=='强' and a:
        score+=10;sigs.append(f"客队攻击强(场均进{sa.get('gf_avg','?')})→客胜可能")
    # 小组形势战意
    moti_h=calc_motivation(m.get('home',''),kb);moti_a=calc_motivation(m.get('away',''),kb)
    if moti_a=='must_win' and a:score+=15;sigs.append("客队必须赢→战意加成")
    if moti_h=='relaxed' and a:score+=10;sigs.append("主队已出线→可能轮换")
    if score>=30 and d:recs.append({'play':'胜平负','pick':'平','odds':d,'reason':'平赔冷门','cold_type':COLD_TYPE1})
    if score>=25 and a:
        ct=COLD_TYPE1 if h<SUPER_FAVORITE else COLD_TYPE2
        recs.append({'play':'胜平负','pick':'负','odds':a,'reason':'客胜高赔','cold_type':ct})
    return{'score':min(score,100),'signals':sigs,'recs':recs}

def sig_hhad(m):
    l=m.get('hhad_line','');h=m.get('hhad_h');a=m.get('hhad_a')
    if not h:return{'score':0,'signals':[],'recs':[]}
    score=0;sigs=[];recs=[]
    if l=='-1' and h>2.0:score+=30;sigs.append(f"让1球赔率{h}→穿盘信心低[Type2]")
    if l=='-1' and a and a<3.0:score+=25;sigs.append(f"受让方仅{a}→弱队或守住[Type2]")
    if l=='-2':score+=20;sigs.append("让2球深盘→极端[Type2]")
    if l in('+1','+2'):score+=20;sigs.append(f"主队受让{l}→超弱[Type2]")
    if l=='-1' and h>2.0:recs.append({'play':'让球胜平负','pick':'让负','odds':a,'reason':'受让方冷门','cold_type':COLD_TYPE2})
    return{'score':min(score,100),'signals':sigs,'recs':recs}

def sig_ttg(m):
    ttg=m.get('ttg',{})
    if not ttg:return{'score':0,'signals':[],'recs':[]}
    score=0;sigs=[];recs=[]
    t0=ttg.get(0,0);t1=ttg.get(1,0)
    if t0 and t0<12.0:score+=30;sigs.append(f"0球赔率{t0}→闷平风险[Type3]")
    if t1 and t1<5.0:score+=20;sigs.append(f"1球赔率{t1}→进球难产[Type3]")
    if t0:recs.append({'play':'总进球','pick':'0球','odds':t0,'reason':'闷平','cold_type':COLD_TYPE3})
    if t1:recs.append({'play':'总进球','pick':'1球','odds':t1,'reason':'低比分','cold_type':COLD_TYPE3})
    return{'score':min(score,100),'signals':sigs,'recs':recs}

def sig_crs(m, kb):
    crs=m.get('crs',{});h=m.get('had_h',0)
    if not crs:return{'score':0,'signals':[],'recs':[]}
    score=0;sigs=[];recs=[]
    c00=crs.get('0:0',0);c11=crs.get('1:1',0);c01=crs.get('0:1',0)
    sig_count=0
    if c00 and c00<12.0 and h<1.80:
        score+=15;sigs.append(f"0:0赔率{c00}→强队或闷平[Type1]");sig_count+=1
    if c11 and c11<7.0 and h<1.50:
        score+=15;sigs.append(f"1:1赔率{c11}→被逼平[Type1]");sig_count+=1
    if c01 and c01<10.0 and h<1.50:
        ct=COLD_TYPE1 if h<SUPER_FAVORITE else COLD_TYPE2
        score+=18;sigs.append(f"0:1赔率{c01}→爆冷客胜[{ct}]");sig_count+=1
    # 扩展冷门比分：赔率>8且<200，但只计TOP5，单信号分值降低
    cold_crs_scores=[]
    for sk,so in crs.items():
        if sk in('0:0','1:1','0:1','胜其他','负其他'):continue
        if ':' in sk and so and 8<so<200:
            cold_crs_scores.append((sk,so))
    cold_crs_scores.sort(key=lambda x:-x[1])
    for i,(sk,so) in enumerate(cold_crs_scores):
        if i>=5:break
        score+=5;sigs.append(f"{sk}赔率{so}→冷门比分")
        recs.append({'play':'比分','pick':sk,'odds':so,'reason':'冷门比分','cold_type':COLD_TYPE2})
        sig_count+=1
    # 胜其他/负其他
    cwo=crs.get('胜其他',0);clo=crs.get('负其他',0)
    if cwo and cwo<80.0 and h and h<1.50:
        score+=15;sigs.append(f"胜其他赔率{cwo}→大比分赢球空间");sig_count+=1
    if clo and clo<80.0 and h and h<1.80:
        score+=20;sigs.append(f"负其他赔率{clo}→大比分爆冷空间");sig_count+=1
        recs.append({'play':'比分','pick':'负其他','odds':clo,'reason':'大比分客胜爆冷','cold_type':COLD_TYPE2})
    # 知识库球队战绩
    tf_h=fuzzy_team(m.get('home',''),kb)
    tf_a=fuzzy_team(m.get('away',''),kb)
    if tf_h.get('losses',0)>=3 and c01:score+=15;sigs.append(f"主队近{tf_h['losses']}败");sig_count+=1
    if tf_a.get('wins',0)>=4 and c01:score+=15;sigs.append(f"客队近{tf_a['wins']}胜");sig_count+=1
    # 攻防差值
    sh=calc_team_strength(tf_h);sa=calc_team_strength(tf_a)
    gd_diff=sa.get('gd_avg',0)-sh.get('gd_avg',0)
    if gd_diff>0.5 and c01:score+=10;sigs.append(f"客队攻防差值优+{gd_diff:.1f}→客胜比分可能");sig_count+=1
    if c01 and c01<15.0 and h<1.50:recs.append({'play':'比分','pick':'0:1','odds':c01,'reason':'客胜冷门','cold_type':COLD_TYPE2})
    if c11 and c11<8.0 and h<1.50:recs.append({'play':'比分','pick':'1:1','odds':c11,'reason':'平局冷门','cold_type':COLD_TYPE1})
    if c00 and c00<15.0:recs.append({'play':'比分','pick':'0:0','odds':c00,'reason':'闷平','cold_type':COLD_TYPE1})
    # 信号分按触发数量动态计算，不轻易封顶
    final_score = min(score, 80 + sig_count*2)  # 基础80+每多一个信号+2，上限约90-100
    return{'score':min(final_score,100),'signals':sigs,'recs':recs}

def sig_hafu(m):
    hafu=m.get('hafu',{});h=m.get('had_h',0)
    if not hafu:return{'score':0,'signals':[],'recs':[]}
    score=0;sigs=[];recs=[]
    dd=hafu.get('平平',0);da=hafu.get('平负',0);ha=hafu.get('胜负',0)
    if dd and dd<5.0 and h<1.50:score+=25;sigs.append(f"平平{dd}→半场僵局[Type1]")
    if da and da<8.0 and h<1.50:score+=25;sigs.append(f"平负{da}→半平全负[Type2]")
    if ha and ha<40.0 and h<1.50:score+=30;sigs.append(f"胜负{ha}→先赢后输大冷[Type2]")
    if dd and dd<6.0 and h<1.50:recs.append({'play':'半全场','pick':'平平','odds':dd,'reason':'半全场僵局','cold_type':COLD_TYPE1})
    if da and da<10.0 and h<1.50:recs.append({'play':'半全场','pick':'平负','odds':da,'reason':'半平全负','cold_type':COLD_TYPE2})
    return{'score':min(score,100),'signals':sigs,'recs':recs}

def sig_cross(m, allsig):
    high=[n for n,s in allsig.items() if n!='cross' and s['score']>=20]
    n=len(high);score=0;sigs=[]
    if n>=3:score+=40;sigs.append(f"🔥{n}种玩法报警:{','.join(high)}")
    elif n>=2:score+=25;sigs.append(f"{n}种玩法报警:{','.join(high)}")
    return{'score':min(score,100),'signals':sigs,'play_count':n,'alerted':high}

# ═══════════════════════════════════════════
# 3. 综合评分
# ═══════════════════════════════════════════

W={'had':0.15,'hhad':0.10,'ttg':0.12,'crs':0.17,'hafu':0.10,'cross':0.20,'kb':0.08,'oddsdev':0.08}

def score_match(m, kb):
    sigs={'had':sig_had(m,kb),'hhad':sig_hhad(m),'ttg':sig_ttg(m),'crs':sig_crs(m,kb),'hafu':sig_hafu(m)}
    sigs['cross']=sig_cross(m,sigs)
    # kb extra
    kb_s=0;kb_d=[]
    tf_h=fuzzy_team(m.get('home',''),kb)
    tf_a=fuzzy_team(m.get('away',''),kb)
    if tf_h.get('losses',0)>=3:kb_s+=25;kb_d.append(f"主近10场{tf_h['losses']}败")
    if tf_a.get('wins',0)>=4:kb_s+=20;kb_d.append(f"客近10场{tf_a['wins']}胜")
    sigs['kb']={'score':kb_s,'signals':kb_d,'recs':[]}
    # odds dev + 变动追踪
    od_s=0;od_d=[]
    h=m.get('had_h'); match_id=m.get('match_id','')
    if h:
        fair=1/h+1/m.get('had_d',0)+1/m.get('had_a',0)
        dev=abs(1/h/fair-0.5)*100
        if dev>8:od_s=15;od_d.append(f"隐含概率偏离{dev:.0f}%")
    # 赔率变动追踪：对比上次快照
    snapshots=kb.get('odds_snapshots',{})
    if match_id and match_id in snapshots:
        prev=snapshots[match_id]
        ph=prev.get('had_h');pd_=prev.get('had_d');pa=prev.get('had_a')
        if ph and h:
            delta_h=(h-ph)/ph*100
            if abs(delta_h)>=5:
                direction="↓跳水" if delta_h<0 else "↑飙升"
                od_s+=20;od_d.append(f"主胜赔率{direction}{abs(delta_h):.0f}% ({ph:.2f}→{h:.2f})")
                if delta_h>5:od_d.append("庄家拉升主胜→不看好热门")
        if pd_ and m.get('had_d'):
            delta_d=(m['had_d']-pd_)/pd_*100
            if delta_d<-5:od_s+=15;od_d.append(f"平赔跳水{abs(delta_d):.0f}%→防平信号")
        if pa and m.get('had_a'):
            delta_a=(m['had_a']-pa)/pa*100
            if delta_a<-8:od_s+=20;od_d.append(f"客胜赔率跳水{abs(delta_a):.0f}%→冷门预警")
    sigs['oddsdev']={'score':min(od_s,100),'signals':od_d,'recs':[]}
    total=0
    for nm,si in sigs.items():total+=si['score']*W.get(nm,0)
    # 按冷门类型汇总
    type_scores={COLD_TYPE1:0,COLD_TYPE2:0,COLD_TYPE3:0}
    for nm,si in sigs.items():
        for r in si.get('recs',[]):
            ct=r.get('cold_type','')
            if ct in type_scores:type_scores[ct]+=si['score']*W.get(nm,0)
    dominant_type=max(type_scores,key=type_scores.get) if any(type_scores.values()) else ''
    all_recs=[]
    for nm,si in sigs.items():
        for r in si.get('recs',[]):all_recs.append({**r,'source':nm})
    # 排序：信号强度×log(赔率)×玩法权重
    PLAY_WEIGHT = {'胜平负':1.5,'总进球':1.3,'半全场':1.2,'让球胜平负':1.1,'比分':1.0}
    import math
    def rec_score(r):
        src=r.get('source','')
        si_score=sigs.get(src,{}).get('score',0)
        odds=r.get('odds',1)
        pw=PLAY_WEIGHT.get(r.get('play',''),1.0)
        return pw * (si_score * math.log(max(odds,1.1),2)) if si_score>0 else pw*odds
    all_recs.sort(key=rec_score, reverse=True)
    # 多样性穿插：前6条推荐中至少2条非比分，确保各玩法可见
    score_recs=[r for r in all_recs if r['play']=='比分']
    other_recs=[r for r in all_recs if r['play']!='比分']
    balanced_recs=[]
    si,oi=0,0
    while len(balanced_recs)<12:
        # 交替插入：比分→非比分→比分→非比分
        if len(balanced_recs)%2==0:
            if si<len(score_recs):balanced_recs.append(score_recs[si]);si+=1
            elif oi<len(other_recs):balanced_recs.append(other_recs[oi]);oi+=1
            else:break
        else:
            if oi<len(other_recs):balanced_recs.append(other_recs[oi]);oi+=1
            elif si<len(score_recs):balanced_recs.append(score_recs[si]);si+=1
            else:break
    all_recs=balanced_recs
    lv="✅正常"
    if total>=50:lv="🔥🔥🔥极高"
    elif total>=35:lv="🔥🔥高"
    elif total>=22:lv="🔥中等"
    elif total>=10:lv="⚠️低"
    return{'match':m,'signals':sigs,'total':round(total,1),'level':lv,'recs':all_recs,
           'cold_types':type_scores,'dominant_type':dominant_type}

# ═══════════════════════════════════════════
# 4. 方案生成 (v3.2: 激进+稳健双方案，ABC三腿递进逻辑)
# ═══════════════════════════════════════════

# 玩法稳定性排序：总进球/胜平负 > 半全场 > 让球 > 比分
STABLE_PLAYS = ['总进球','胜平负']
MID_PLAYS = ['半全场','让球胜平负']
HIGH_PLAYS = ['比分']

def _pick_by_odds_range(avail, odds_min, odds_max, used, plays=None, exclude_matches=None):
    """从avail中选赔率在[odds_min, odds_max]内的最佳推荐，支持玩法过滤和比赛去重"""
    candidates = []
    for m in avail:
        for r in m.get('recs', []):
            if odds_min <= r.get('odds', 0) <= odds_max:
                if plays and r['play'] not in plays: continue
                key = f"{r['play']}:{r['pick']}"
                if key in used: continue
                mid = m['match']['match_num_str']
                if exclude_matches and mid in exclude_matches: continue
                # 评分：信号分越高的推荐排前面
                src = r.get('source', '')
                sig = m.get('signals', {}).get(src, {}).get('score', 0)
                candidates.append((m, r, sig))
    candidates.sort(key=lambda x: (-x[2], -x[1]['odds']))  # 信号分优先，同分选高赔
    return candidates

def _pick_best_cold(avail, used, min_odds=6.0, plays=None, exclude_matches=None):
    """
    博冷选项：选信号最强的冷门推荐，不设赔率上限。
    按「信号分×赔率」综合排序，信号越强+赔率合理=最优。
    单项赔率上限100（超出视为极小概率事件，不纳入推荐）。
    """
    candidates = []
    for m in avail:
        for r in m.get('recs', []):
            odds = r.get('odds', 0)
            if odds < min_odds: continue
            if odds > 100: continue  # 单项上限100，排除极小概率事件
            if plays and r['play'] not in plays: continue
            key = f"{r['play']}:{r['pick']}"
            if key in used: continue
            mid = m['match']['match_num_str']
            if exclude_matches and mid in exclude_matches: continue
            # 综合评分 = 信号分 × log(赔率)，对数压缩极端高赔的影响
            import math
            src = r.get('source', '')
            sig = m.get('signals', {}).get(src, {}).get('score', 0)
            composite = sig * math.log(odds, 2) if sig > 0 else odds
            candidates.append((m, r, composite))
    candidates.sort(key=lambda x: -x[2])
    return candidates

def _make_bet(m, r, suffix=''):
    return {
        'match': f"{m['match']['match_num_str']} {m['match']['home']}vs{m['match']['away']}",
        'play': r['play'], 'pick': r['pick'], 'odds': r['odds'],
        'reason': r.get('reason', '') + suffix, 'level': m['level']
    }

def _gen_aggressive_plan(scored, avail):
    """
    激进方案 v3.2：ABC三腿递进逻辑
    A-2串1(4元): 一腿稳健(非比分玩法，赔率3-6) + 一腿博冷(不限玩法，信号×赔率最强)
    B-单关(2元): 独立博冷，不限玩法，按信号×赔率综合最强（上限100）
    C-2串1(4元): 中等冷门双串，强制包含至少一腿非比分，赔率4-15
    """
    plan = {'label': '🔥 激进方案', 'parts': [], 'total_cost': 0}
    used = set()

    # ── A腿：一稳一冷 ──
    # 稳底：非比分玩法（总进球/胜平负/半全场/让球），赔率3-6
    stable = _pick_by_odds_range(avail, 3.0, 6.0, used, plays=STABLE_PLAYS+MID_PLAYS)
    a_bets = []
    a_matches = set()
    if stable:
        m, r, _ = stable[0]
        a_bets.append(_make_bet(m, r, '[稳底]'))
        used.add(f"{r['play']}:{r['pick']}")
        a_matches.add(m['match']['match_num_str'])
        # 冷腿：不限玩法，不限赔率上限(≤100)，信号最强
        cold = _pick_best_cold(avail, used, min_odds=6.0, exclude_matches=a_matches)
        if cold:
            m, r, _ = cold[0]
            a_bets.append(_make_bet(m, r, '[博冷]'))
            used.add(f"{r['play']}:{r['pick']}")
            a_matches.add(m['match']['match_num_str'])
    if len(a_bets) >= 2:
        oa = a_bets[0]['odds'] * a_bets[1]['odds']
        plan['parts'].append({
            'label': 'A-2串1', 'type': '2串1', 'bets': a_bets, 'cost': 4,
            'odds_x': round(oa, 1), 'ret': round(2 * oa, 1),
            'note': f"稳底托冷 | {a_bets[0]['play']}({a_bets[0]['odds']})×{a_bets[1]['play']}({a_bets[1]['odds']})"
        })
        plan['total_cost'] += 4

    # ── B腿：独立博冷，不限玩法，信号×赔率综合最强 ──
    cold = _pick_best_cold(avail, used, min_odds=8.0)
    if cold:
        m, r, _ = cold[0]
        plan['parts'].append({
            'label': 'B-单关', 'type': '单关',
            'bets': [_make_bet(m, r, '[单点博冷]')],
            'cost': 2, 'odds_x': r['odds'], 'ret': round(2 * r['odds'], 1),
            'note': f"独立博冷 | {r['play']}({r['odds']})"
        })
        plan['total_cost'] += 2
        used.add(f"{r['play']}:{r['pick']}")

    # ── C腿：中等冷门双串，强制至少一腿非比分 ──
    # 第一腿：赔率4-15，优先非比分
    non_score = _pick_by_odds_range(avail, 4.0, 15.0, used, plays=STABLE_PLAYS+MID_PLAYS)
    c_bets = []
    c_matches = set()
    if non_score:
        m, r, _ = non_score[0]
        c_bets.append(_make_bet(m, r, '[平衡]'))
        used.add(f"{r['play']}:{r['pick']}")
        c_matches.add(m['match']['match_num_str'])
    # 第二腿：赔率4-15，不限玩法，不同比赛
    rest = _pick_by_odds_range(avail, 4.0, 15.0, used, exclude_matches=c_matches)
    for m, r, _ in rest:
        if len(c_bets) >= 2: break
        mid_key = m['match']['match_num_str']
        if mid_key in c_matches: continue
        c_bets.append(_make_bet(m, r))
        used.add(f"{r['play']}:{r['pick']}")
        c_matches.add(mid_key)
    if len(c_bets) >= 2:
        oc = c_bets[0]['odds'] * c_bets[1]['odds']
        plan['parts'].append({
            'label': 'C-2串1', 'type': '2串1', 'bets': c_bets, 'cost': 4,
            'odds_x': round(oc, 1), 'ret': round(2 * oc, 1),
            'note': f"中等冷门 | {c_bets[0]['play']}({c_bets[0]['odds']})×{c_bets[1]['play']}({c_bets[1]['odds']})"
        })
        plan['total_cost'] += 4

    return plan

def _gen_conservative_plan(scored, avail):
    """
    稳健方案 v3.2：ABC三腿递进逻辑
    A-2串1(4元): 两腿均为稳健玩法(赔率3-6，总进球/胜平负)，不同比赛，综合9-36x
    B-单关(2元): 中等冷门(赔率6-12)，单关博冷
    C-2串1(4元): 一稳一冷平衡(赔率4-8)，综合16-64x
    """
    plan = {'label': '🛡️ 稳健方案', 'parts': [], 'total_cost': 0}
    used = set()

    # ── A腿：纯稳健双串 ──
    stable = _pick_by_odds_range(avail, 3.0, 6.0, used, plays=STABLE_PLAYS)
    a_bets = []
    a_matches = set()
    for m, r, _ in stable:
        if len(a_bets) >= 2: break
        mid_key = m['match']['match_num_str']
        if mid_key in a_matches: continue
        a_bets.append(_make_bet(m, r, '[稳]'))
        used.add(f"{r['play']}:{r['pick']}")
        a_matches.add(mid_key)
    if len(a_bets) >= 2:
        oa = a_bets[0]['odds'] * a_bets[1]['odds']
        plan['parts'].append({
            'label': 'A-2串1', 'type': '2串1', 'bets': a_bets, 'cost': 4,
            'odds_x': round(oa, 1), 'ret': round(2 * oa, 1),
            'note': f"稳健双选 | {a_bets[0]['play']}×{a_bets[1]['play']}"
        })
        plan['total_cost'] += 4

    # ── B腿：中等冷门单关 ──
    cold = _pick_by_odds_range(avail, 6.0, 12.0, used, plays=MID_PLAYS+HIGH_PLAYS)
    if not cold:
        cold = _pick_by_odds_range(avail, 6.0, 12.0, used)
    if cold:
        m, r, _ = cold[0]
        plan['parts'].append({
            'label': 'B-单关', 'type': '单关',
            'bets': [_make_bet(m, r, '[博冷]')],
            'cost': 2, 'odds_x': r['odds'], 'ret': round(2 * r['odds'], 1),
            'note': f"中等博冷 | {r['play']}({r['odds']})"
        })
        plan['total_cost'] += 2
        used.add(f"{r['play']}:{r['pick']}")

    # ── C腿：平衡串关(赔率4-8) ──
    balance = _pick_by_odds_range(avail, 4.0, 8.0, used)
    c_bets = []
    c_matches = set()
    for m, r, _ in balance:
        if len(c_bets) >= 2: break
        mid_key = m['match']['match_num_str']
        if mid_key in c_matches: continue
        c_bets.append(_make_bet(m, r))
        used.add(f"{r['play']}:{r['pick']}")
        c_matches.add(mid_key)
    if len(c_bets) >= 2:
        oc = c_bets[0]['odds'] * c_bets[1]['odds']
        plan['parts'].append({
            'label': 'C-2串1', 'type': '2串1', 'bets': c_bets, 'cost': 4,
            'odds_x': round(oc, 1), 'ret': round(2 * oc, 1),
            'note': f"平衡串关 | {c_bets[0]['play']}×{c_bets[1]['play']}"
        })
        plan['total_cost'] += 4

    return plan

def gen_plan(scored):
    avail = [m for m in scored if m['match']['status'] == 'Selling']
    if len(avail) < 2:
        return {'error': '可投注比赛不足2场'}
    avail.sort(key=lambda x: -x['total'])
    aggressive = _gen_aggressive_plan(scored, avail)
    conservative = _gen_conservative_plan(scored, avail)
    return {
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'plans': [aggressive, conservative]
    }

# ═══════════════════════════════════════════
# 5. 输出
# ═══════════════════════════════════════════

def print_analysis(scored,kb):
    print("="*80)
    print(f"   🌍 世界杯冷门预测 v3.2 | {datetime.now().strftime('%m-%d %H:%M')} | 知识库:{len(kb.get('matches',[]))}场/{len(kb.get('teams',{}))}队")
    print("="*80)
    for i,sm in enumerate(sorted(scored,key=lambda x:-x['total']),1):
        m=sm['match']
        print(f"\n{'─'*80}\n  #{i} {m['match_num_str']} {m['home']}vs{m['away']}")
        print(f"  {m['match_date']} {m['match_time']} | 状态:{m['status']}")
        hs=f"{m.get('had_h','?')}/{m.get('had_d','?')}/{m.get('had_a','?')}" if m.get('had_h') else "无"
        print(f"  胜平负:{hs} | 让球:{m.get('hhad_line','?')}")
        tf_h=fuzzy_team(m['home'],kb)
        tf_a=fuzzy_team(m['away'],kb)
        if tf_h.get('form') or tf_a.get('form'):
            print(f"  主队战绩:{tf_h.get('form','?')} | 客队:{tf_a.get('form','?')}")
        print(f"\n  🎯 冷门评分:{sm['total']}/100 → {sm['level']}")
        if sm.get('dominant_type'):
            print(f"  🏷️ 主导冷门:{sm['dominant_type']}")
            parts=[]
            for ct,cs in sm.get('cold_types',{}).items():
                if cs>0:
                    short=ct.split('-')[1] if '-' in ct else ct
                    parts.append(f"{short}:{cs:.1f}分")
            if parts:print(f"   {' | '.join(parts)}")
        print(f"\n  📊 八维信号:")
        for nm,si in sm['signals'].items():
            if nm=='cross':continue
            bar='█'*min(int(si['score']/5),20)+'░'*max(20-int(si['score']/5),0)
            print(f"   {nm:<14} [{bar}] {si['score']:.0f}分")
            for d in si.get('signals',[])[:2]:print(f"   {'':>16} {d}")
        recs=sm.get('recs',[])
        if recs:
            print(f"\n  💡 推荐:");[print(f"   [{r['play']}]{r['pick']}@{r['odds']} — {r['reason']}") for r in recs[:4]]
    print(f"\n{'='*80}\n")

def print_plan(plan):
    print("="*80);print("        🎯 今日冷门方案 v3.2");print("="*80)
    if'error'in plan:print(f"  ⚠️ {plan['error']}");return
    total_all=0
    for p in plan.get('plans',[]):
        label=p.get('label','方案')
        print(f"\n  ▶ {label}")
        print(f"  💰 投入:{p['total_cost']}元")
        total_all+=p['total_cost']
        for part in p.get('parts',[]):
            print(f"\n  ┌ {part['label']}:{part['type']}")
            print(f"  │ {part['note']} | {part['cost']}元 | ~{part['odds_x']}x | 回{part['ret']}元")
            for b in part['bets']:print(f"  │ {b['match']}\n  │   [{b['play']}]{b['pick']}@{b['odds']} {b['reason']}")
        print(f"\n  📋 {label}合计:{p['total_cost']}元")
    print(f"\n  💰 总投入:{total_all}元 | ⚠️ 理性投注！");print("="*80)

def calc_trigger_time(matches):
    """计算最优触发时间：取最早开赛时间T，返回T-1小时。如果T-1h已过则返回None（立即运行）"""
    from datetime import timedelta
    earliest = None
    for m in matches:
        mt = m.get('match_time', ''); md = m.get('match_date', '')
        if mt and md:
            try:
                # 容错不同格式
                ts = mt if len(mt) == 8 else (mt + ':00' if len(mt) == 5 else mt)
                kickoff = datetime.strptime(f"{md} {ts}", '%Y-%m-%d %H:%M:%S')
                if earliest is None or kickoff < earliest:
                    earliest = kickoff
            except: continue
    if earliest:
        trigger = earliest - timedelta(hours=1)
        now = datetime.now()
        if trigger > now:
            return trigger
    return None

# ═══════════════════════════════════════════
# 6. 主入口
# ═══════════════════════════════════════════

def main():
    print("🔄 获取体彩数据 + 加载知识库...")
    kb=load_knowledge_base()
    # 赛果回写
    try:
        new_results=fetch_results()
        if new_results:
            added=update_kb_results(kb, new_results)
            if added>0:save_kb(kb)
    except: pass
    try:
        raw=fetch_sporttery()
        matches=parse_matches(raw)
    except Exception as e:
        print(f"❌ {e}");return
    # 赔率时效性：动态触发时间
    trigger=calc_trigger_time(matches)
    if trigger:
        now=datetime.now()
        wait_min=(trigger-now).total_seconds()/60
        print(f"⏰ 最早开赛:{trigger.strftime('%m-%d %H:%M')}（{wait_min:.0f}分钟后）")
        if os.environ.get('WC_AUTO_SCHEDULE')=='1' and wait_min>5:
            print(f"📋 自动调度到赛前1小时执行，当前跳过")
            return
    selling=[m for m in matches if m.get('status')=='Selling']
    if not selling:print("❌ 无在售比赛");return
    today=datetime.now().strftime('%Y-%m-%d')
    today_m=[m for m in selling if m.get('match_date')==today]
    if not today_m:
        dates=sorted(set(m.get('match_date') for m in selling if m.get('match_date')))
        if dates:today_m=[m for m in selling if m.get('match_date')==dates[0]]
        print(f"⚠️ 无今日比赛，用{dates[0]}")
    print(f"📊 获取{len(today_m)}场在售比赛\n")
    # 保存当前赔率快照（供下次变动追踪）
    snapshots = kb.get('odds_snapshots', {})
    for m in matches:
        mid = m.get('match_id', '')
        if mid:
            snapshots[mid] = {
                'had_h': m.get('had_h'), 'had_d': m.get('had_d'), 'had_a': m.get('had_a'),
                'hhad_h': m.get('hhad_h'), 'hhad_d': m.get('hhad_d'), 'hhad_a': m.get('hhad_a'),
                'hhad_line': m.get('hhad_line'), 'time': datetime.now().strftime('%m-%d %H:%M')
            }
    kb['odds_snapshots'] = snapshots
    kb['patterns']['updated'] = datetime.now().strftime('%Y-%m-%d')
    save_kb(kb)
    scored=[score_match(m,kb) for m in today_m]
    print_analysis(scored,kb)
    plan=gen_plan(scored)
    print_plan(plan)
    return scored,plan,kb

if __name__=='__main__':
    main()
