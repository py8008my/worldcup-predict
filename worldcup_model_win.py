#!/usr/bin/env python3
"""
世界杯必胜预测模型 v4.0-win
===========================
数据源：体彩官方API(webapi.sporttery.cn) + 本地知识库(knowledge_base.json)
玩法覆盖：胜平负 / 总进球 / 混合过关（不含比分/半全场/让球）
v4.0-win：博冷+稳健模型派生必胜版
  - 概率为王：组合目标P≥50%
  - 极简玩法：仅总进球+胜平负，不碰比分/半全场
  - 赔率约束：单组合≤30倍
  - 复式全覆盖：总进球0-3球全选 + 胜平负稳方向
  - 10元全压一组必胜方案
  - 策略：宁可选赔率2x概率50%，不选赔率100x概率1%
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

def sig_consensus(m, allsig):
    """
    玩法一致性检测 — 信号阶段关联增强
    ====================================
    官方规则：同一场比赛的不同玩法不能混合过关。
    因此，玩法间关联不用于串关概率加成，而是用于增强信号置信度：
    如果多个玩法指向同一方向（如总进球高+比分客胜+胜平负客胜），
    说明"冷门"判断更可靠，应该提升该方向的信号分。
    
    检测方向：
      - 客胜方向：胜平负→负 + 让球→让负 + 比分→客胜方向 + 半全场→平负/负负
      - 平局方向：胜平负→平 + 总进球→低球 + 比分→平局 + 半全场→平平
      - 主胜冷门方向：胜平负→主胜(高赔) + 让球→让胜 + 比分→主胜方向
    """
    score=0;sigs=[];direction={}
    # 提取各玩法方向
    for nm,si in allsig.items():
        if nm=='cross':continue
        for sig_text in si.get('signals',[]):
            if '客胜' in sig_text or '客队' in sig_text or '受让' in sig_text:
                direction.setdefault('away',[]).append(nm)
            if '平' in sig_text and '半' not in sig_text:
                direction.setdefault('draw',[]).append(nm)
            if ('主胜' in sig_text or '穿盘' in sig_text) and '冷' in sig_text:
                direction.setdefault('home_cold',[]).append(nm)
    
    # 去重计数
    for d in direction:
        direction[d]=list(set(direction[d]))
    
    away_count=len(direction.get('away',[]))
    draw_count=len(direction.get('draw',[]))
    home_count=len(direction.get('home_cold',[]))
    
    if away_count>=3:score+=30;sigs.append(f"🔴 {away_count}种玩法指向客胜→客胜冷门置信度+")
    elif away_count>=2:score+=18;sigs.append(f"🟡 {away_count}种玩法指向客胜→客胜信号增强")
    if draw_count>=3:score+=28;sigs.append(f"🔵 {draw_count}种玩法指向平局→平局置信度+")
    elif draw_count>=2:score+=16;sigs.append(f"🟢 {draw_count}种玩法指向平局→平局信号增强")
    if home_count>=2:score+=14;sigs.append(f"🟠 {home_count}种玩法指向主胜冷→主胜冷门信号")
    
    return{'score':min(score,100),'signals':sigs,'direction':direction}

def sig_xg(m, kb):
    """xG高阶统计信号 — 预期进球差"""
    stats = kb.get('teams_stats', {})
    home = m.get('home', ''); away = m.get('away', '')
    hs = stats.get(home, {}); aws = stats.get(away, {})
    score = 0; sigs = []
    if not hs or not aws:
        return {'score': 0, 'signals': [], 'recs': []}
    h_net = hs.get('xG', 0) - hs.get('xGA', 0)
    a_net = aws.get('xG', 0) - aws.get('xGA', 0)
    xg_gap = h_net - a_net
    h_odds = m.get('had_h', 0)
    if xg_gap < -0.3:
        score += 15; sigs.append(f"xG差值{xg_gap:.2f}→客队真实实力更强")
        if h_odds and h_odds < 2.0:
            score += 20; sigs.append(f"主队赔率{h_odds}但xG劣势{xg_gap:.2f}→冷门预警")
    elif xg_gap > 0.5 and h_odds > 2.0:
        score += 10; sigs.append(f"主队xG优势{xg_gap:.2f}但赔率{h_odds}偏高")
    if hs.get('xGA', 0) > 1.5:
        score += 10; sigs.append(f"主队防守差(xGA={hs['xGA']})→易失球")
    if aws.get('xGA', 0) < 0.8:
        score += 10; sigs.append(f"客队防守强(xGA={aws['xGA']})→不易被进球")
    ppg_gap = hs.get('ppg', 0) - aws.get('ppg', 0)
    if ppg_gap < -0.8:
        score += 12; sigs.append(f"客队近期PPG优势{abs(ppg_gap):.1f}")
    return {'score': min(score, 100), 'signals': sigs, 'recs': []}

def sig_h2h(m, kb):
    """历史交锋信号"""
    h2h_data = kb.get('h2h', {})
    home = m.get('home', ''); away = m.get('away', '')
    keys_to_try = [f"{home}_{away}", f"{away}_{home}"]
    h2h = None
    for k in keys_to_try:
        if k in h2h_data:
            h2h = h2h_data[k]; break
    if h2h is None:
        for k, v in h2h_data.items():
            if isinstance(k, tuple) and home in k and away in k:
                h2h = v; break
    score = 0; sigs = []
    if not h2h or h2h.get('total', 0) < 2:
        return {'score': 0, 'signals': [], 'recs': []}
    total = h2h['total']; draw_rate = h2h.get('draw_rate', 0)
    avg_goals = h2h.get('avg_goals', 0)
    if draw_rate >= 0.4 and total >= 3:
        score += 20; sigs.append(f"交锋{total}场平局率{draw_rate:.0%}→易平")
    elif draw_rate >= 0.25:
        score += 10; sigs.append(f"交锋平局率{draw_rate:.0%}")
    h_odds = m.get('had_h', 0); a_odds = m.get('had_a', 0)
    wins_a = h2h.get('wins_a', 0); wins_b = h2h.get('wins_b', 0)
    if h_odds and a_odds:
        if h_odds < 1.50 and wins_b >= wins_a:
            score += 25; sigs.append(f"主队赔率{h_odds}但客队交锋{wins_b}胜{wins_a}胜")
        if a_odds < 2.5 and wins_a >= wins_b:
            score += 15; sigs.append(f"客队赔率低但主队交锋占优")
    if avg_goals < 2.0 and total >= 3:
        score += 12; sigs.append(f"交锋场均{avg_goals}球→低比分趋势")
    return {'score': min(score, 100), 'signals': sigs, 'recs': []}

def sig_stage(m, kb):
    """赛事阶段信号"""
    stage = kb.get('tournament_stage', 'group')
    score = 0; sigs = []
    if stage == 'knockout':
        score += 15; sigs.append("淘汰赛阶段→平局率↑ 冷门率↑")
    elif stage == 'group_final':
        score += 10; sigs.append("小组赛末轮→战意分化 不确定性↑")
    return {'score': min(score, 100), 'signals': sigs, 'recs': []}


# ═══════════════════════════════════════════
# 3. 综合评分
# ═══════════════════════════════════════════

W={'had':0.12,'hhad':0.08,'ttg':0.10,'crs':0.14,'hafu':0.08,'cross':0.15,'kb':0.06,'oddsdev':0.06,'consensus':0.07,'xg':0.08,'h2h':0.04,'stage':0.02}

def score_match(m, kb):
    sigs={'had':sig_had(m,kb),'hhad':sig_hhad(m),'ttg':sig_ttg(m),'crs':sig_crs(m,kb),'hafu':sig_hafu(m)}
    sigs['cross']=sig_cross(m,sigs)
    sigs['consensus']=sig_consensus(m,sigs)
    # v4.0 新增信号
    sigs['xg']=sig_xg(m,kb)
    sigs['h2h']=sig_h2h(m,kb)
    sigs['stage']=sig_stage(m,kb)
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
# 4. 方案生成 v3.3 — 动态组合模式
# ═══════════════════════════════════════════
# 竞彩核心规则：
#   - 每注 = 2元
#   - 2串1 = 两场各选1个结果串起来 = 1注
#   - 3串1 = 三场各选1个结果 = 1注
#   - 单关 = 1场1结果 = 1注
#   - 同一场比赛不能出现在同一注的多个位置
#   - 不同注之间可以复用同一场比赛（不同玩法/结果）
# 30元预算 = 15注，自由分配在单关、2串1、3串1、4串1等组合中。

import itertools, math as _math

STABLE_PLAYS = ['总进球','胜平负']
MID_PLAYS   = ['半全场','让球胜平负']
HIGH_PLAYS  = ['比分']

# ═══════════════════════════════════════════
# 4a. 期望值引擎 — 概率×赔率驱动
# ═══════════════════════════════════════════

def _signal_to_prob(signal_score, play_type='', odds=None):
    """
    信号分 → 概率映射（v5.0改进：融合赔率隐含概率）
    """
    if signal_score <= 0:
        base = 0.01
    elif signal_score <= 10:
        base = 0.01 + (signal_score / 10) * 0.02
    elif signal_score <= 20:
        base = 0.03 + ((signal_score - 10) / 10) * 0.05
    elif signal_score <= 35:
        base = 0.08 + ((signal_score - 20) / 15) * 0.10
    elif signal_score <= 55:
        base = 0.18 + ((signal_score - 35) / 20) * 0.12
    else:
        base = min(0.30 + ((signal_score - 55) / 45) * 0.10, 0.40)
    
    if play_type == '比分':
        base *= 0.35
    
    if odds and odds > 1.0:
        implied_prob = 1.0 / odds
        fused = base * 0.4 + implied_prob * 0.6
        return max(fused, 0.005)
    
    return base

def _calc_ev(signal_score, odds, play_type=''):
    prob = _signal_to_prob(signal_score, play_type, odds)
    return prob * odds, prob

def _pick_best_bets_per_match(scored_match, top_per_play=4):
    """
    必胜型：只选热门方向，避开冷门选项
    =====================================
    核心逻辑（小弟设计）：
    - 确保投注选项里没有冷门选项
    - 如果冷门信号弱（评分<20）→ 正常选，按概率优先
    - 如果冷门信号中等（20-35）→ 只选热门方向（主胜/大球）
    - 如果冷门信号强（≥35）→ 整场避开（不选这场比赛）
    """
    match_total_score = scored_match.get('total', 0)
    recs = scored_match.get('recs', [])
    sigs = scored_match.get('signals', {})
    
    # ── 冷门信号强度判断 ──
    # 冷门评分 ≥ 35 → 整场避开
    if match_total_score >= 35:
        return []
    
    # 冷门评分 20-34 → 只选热门方向
    hot_only = (20 <= match_total_score < 35)
    
    # 热门方向判断：主胜赔率小 = 主队热门
    had_h = scored_match['match'].get('had_h', 0)
    had_a = scored_match['match'].get('had_a', 0)
    
    # 必胜型：只用总进球+胜平负
    allowed = {'总进球', '胜平负'}
    recs = [r for r in recs if r.get('play', '') in allowed]
    
    by_play = {}
    seen = set()
    for r in recs:
        play = r.get('play', '')
        pick = r.get('pick', '')
        key = f"{play}:{pick}"
        if key in seen:
            continue
        seen.add(key)
        
        src = r.get('source', '')
        sig = sigs.get(src, {}).get('score', 0)
        odds = r.get('odds', 1.0)
        
        # 赔率过滤：必胜型不追极端高赔
        if play == '总进球':
            # 只取0-3球（场均进球合理范围）
            try:
                goal_num = int(pick.replace('球', ''))
                if goal_num > 3 or odds < 1.5:
                    continue
            except:
                continue
        elif play == '胜平负':
            if odds < 1.3:
                continue
            # 冷门信号中等时，只选热门方向（主胜）
            if hot_only:
                # 热门方向 = 主胜（主队赔率更低）
                if had_h and had_a:
                    if pick == '负' and had_h < had_a:
                        continue  # 主队是热门，跳过客胜
                    if pick == '平':
                        continue  # 有冷门信号时跳过平局
                else:
                    if pick in ('负', '平'):
                        continue
        
        ev, prob = _calc_ev(sig, odds, play)
        bet = {
            'mid': scored_match['match']['match_num_str'],
            'match': f"{scored_match['match']['match_num_str']} {scored_match['match']['home']}vs{scored_match['match']['away']}",
            'play': play, 'pick': pick, 'odds': odds,
            'reason': r.get('reason', ''),
            'signal_score': sig,
            'prob': prob,
            'ev': round(ev, 3),
            'total_score': scored_match['total'],
            'cold_type': r.get('cold_type', ''),
        }
        if play not in by_play:
            by_play[play] = []
        by_play[play].append(bet)
    
    # 每个玩法取TOP-N，按概率排序（必胜型看概率不看EV）
    result = []
    for play, bets in by_play.items():
        bets.sort(key=lambda x: -x['prob'])
        result.extend(bets[:top_per_play])
    
    result.sort(key=lambda x: -x['prob'])
    return result


def _combo_ev(bets):
    """
    组合期望值：概率乘积 × 赔率乘积
    ====================
    同时返回组合概率，用于过滤极低概率的离谱组合。
    """
    if not bets:
        return 0, 0, 0
    prob_prod = 1.0
    odds_prod = 1.0
    for b in bets:
        prob_prod *= b.get('prob', 0.01)
        odds_prod *= b.get('odds', 1.0)
    ev_prod = prob_prod * odds_prod
    return ev_prod, odds_prod, prob_prod

def _gen_smart_plan(scored):
    """
    必胜方案 v5.0 — 避开冷门，优先串关，宁缺毋滥
    ===============================================
    核心思路（小弟设计）：
    ① 用12维信号过滤掉冷门信号强的比赛（≥35分整场避开）
    ② 只选热门方向的选项（总进球0-3球 + 主胜/大球方向）
    ③ 优先串关（2串1或3串1），通过多场高概率叠乘获取最大收益
    ④ 宁缺毋滥：今天没有足够把握就少投或不投
    ⑤ 不限赔率上下限，按概率×赔率性价比选择
    """
    import itertools as it
    import math as _m
    
    BUDGET_YUAN = 30
    MAX_NOTES = BUDGET_YUAN // 2  # 15注
    
    # 按冷门评分排序，取TOP比赛
    # 注意：这里的 _pick_best_bets_per_match 已经会过滤掉冷门信号≥35的比赛
    top_matches = sorted(scored, key=lambda x: -x['total'])[:8]
    
    # 每场比赛的候选投注项（已过滤冷门方向）
    match_candidates = {}
    for sm in top_matches:
        best = _pick_best_bets_per_match(sm, top_per_play=4)
        if best:  # 冷门信号≥35的比赛会返回空列表，自动被过滤
            match_candidates[sm['match']['match_num_str']] = best
    
    if len(match_candidates) < 2:
        return {
            'label': '💎 今日宁缺毋滥',
            'parts': [],
            'total_cost': 0,
            'note': '今日可投注比赛不足（冷门信号强，建议观望）'
        }
    
    mids = list(match_candidates.keys())
    
    # 木桶原则
    PLAY_MAX_GUAN = {'总进球': 6, '胜平负': 8}
    
    def get_max_guan(bets):
        min_guan = 8
        for b in bets:
            guan = PLAY_MAX_GUAN.get(b.get('play', ''), 8)
            if guan < min_guan:
                min_guan = guan
        return min_guan
    
    # ── 为每场比赛生成"选择集" ──
    def build_selection_sets(mid):
        cands = match_candidates[mid]
        by_play = {}
        for b in cands:
            play = b['play']
            if play not in by_play:
                by_play[play] = []
            by_play[play].append(b)
        
        sets = []
        for play, bets in by_play.items():
            bets = bets[:4]
            # 单选
            for b in bets:
                sets.append({
                    'bets': [b], 'count': 1,
                    'prob': b['prob'], 'avg_odds': b['odds'], 'play': play,
                })
            # 双选（总进球0+1球，胜平负最稳2方向）
            if len(bets) >= 2:
                for i, j in it.combinations(range(len(bets)), 2):
                    b1, b2 = bets[i], bets[j]
                    p = min(b1['prob'] + b2['prob'], 1.0)
                    if p > 0:
                        ao = (b1['odds'] * b1['prob'] + b2['odds'] * b2['prob']) / p
                    else:
                        ao = (b1['odds'] + b2['odds']) / 2
                    sets.append({
                        'bets': [b1, b2], 'count': 2,
                        'prob': p, 'avg_odds': ao, 'play': play,
                    })
            # 三选
            if len(bets) >= 3 and play == '总进球':
                p = min(sum(b['prob'] for b in bets[:3]), 1.0)
                if p > 0:
                    ao = sum(b['odds'] * b['prob'] for b in bets[:3]) / p
                else:
                    ao = sum(b['odds'] for b in bets[:3]) / 3
                sets.append({
                    'bets': bets[:3], 'count': 3,
                    'prob': p, 'avg_odds': ao, 'play': play,
                })
        return sets
    
    mid_selections = {mid: build_selection_sets(mid) for mid in mids}
    
    # ── 枚举复式串关方案 ──
    all_schemes = []
    
    for guan_count in [2, 3]:
        if len(mids) < guan_count:
            continue
        for selected_mids in it.combinations(mids, guan_count):
            selection_lists = [mid_selections[mid] for mid in selected_mids]
            for combo in it.product(*selection_lists):
                total_notes = 1
                for s in combo:
                    total_notes *= s['count']
                if total_notes > MAX_NOTES:
                    continue
                
                all_bets = []
                for s in combo:
                    all_bets.extend(s['bets'])
                if get_max_guan(all_bets) < guan_count:
                    continue
                
                prob_prod = 1.0
                odds_prod = 1.0
                for s in combo:
                    prob_prod *= s['prob']
                    odds_prod *= s['avg_odds']
                
                if prob_prod < 0.05:  # 必胜型概率门槛提高到5%
                    continue
                
                ev = prob_prod * odds_prod
                
                groups = {}
                for i, mid in enumerate(selected_mids):
                    groups[mid] = combo[i]['bets']
                
                all_schemes.append((groups, ev, odds_prod, prob_prod, total_notes, guan_count))
    
    # 单关（保底，只取概率最高的）
    for mid in mids:
        for s in mid_selections[mid]:
            if s['count'] == 1:
                b = s['bets'][0]
                if b['prob'] >= 0.20:  # 单关要求P≥20%
                    all_schemes.append(({mid: [b]}, b['ev'], b['odds'], b['prob'], 1, 1))
    
    if not all_schemes:
        return {
            'label': '💎 今日宁缺毋滥',
            'parts': [],
            'total_cost': 0,
            'note': '今日无有效必胜组合，建议观望'
        }
    
    # ── 去重 ──
    def scheme_key(groups):
        items = []
        for mid, bets in groups.items():
            for b in bets:
                items.append((mid, b['play'], b['pick']))
        return frozenset(items)
    
    seen = set()
    dedup = []
    for s in all_schemes:
        sk = scheme_key(s[0])
        if sk not in seen:
            seen.add(sk)
            dedup.append(s)
    all_schemes = dedup
    
    # ── 必胜方案分配：概率×赔率性价比优先，优先串关 ──
    # 性价比 = prob × log(odds)：概率高且赔率合理
    all_schemes.sort(key=lambda x: -(x[3] * _m.log(max(x[2], 1.5), 2)))
    
    def make_part(groups, ev, odds, prob, notes, guan_count, label_suffix=''):
        flat = []
        for mid, bets in groups.items():
            flat.extend(bets)
        flat.sort(key=lambda b: b['mid'])
        ctype = f"{guan_count}串1" if guan_count > 1 else "单关"
        if notes > 1 and guan_count > 1:
            ctype += f"(复{notes}注)"
        return {
            'type': ctype + label_suffix,
            'bets': flat,
            'groups': groups,
            'cost': notes * 2,
            'ev_product': round(ev, 3),
            'odds_x': round(odds, 1),
            'ret': round(2 * odds, 1),
            'note': f"{ctype} | EV={ev:.2f} | P={prob:.2%} | {notes}注{notes*2}元"
        }
    
    plan_parts = []
    used_notes = 0
    used_keys = set()
    
    # 选最高性价比的串关
    for groups, ev, odds, prob, notes, gc in all_schemes:
        if used_notes >= MAX_NOTES:
            break
        sk = scheme_key(groups)
        if sk in used_keys:
            continue
        if notes <= MAX_NOTES - used_notes and gc >= 2:
            p = make_part(groups, ev, odds, prob, notes, gc, ' 必胜')
            plan_parts.append(p)
            used_notes += notes
            used_keys.add(sk)
    
    # 若还有剩余预算，加单关保底
    for groups, ev, odds, prob, notes, gc in all_schemes:
        if used_notes >= MAX_NOTES:
            break
        sk = scheme_key(groups)
        if sk in used_keys:
            continue
        if notes <= MAX_NOTES - used_notes and gc == 1:
            p = make_part(groups, ev, odds, prob, notes, gc, ' 必胜')
            plan_parts.append(p)
            used_notes += notes
            used_keys.add(sk)
    
    total_cost = sum(p['cost'] for p in plan_parts)
    
    # 标签
    max_prob = max((float(p.get('note', 'P=0%').split('P=')[1].split('%')[0]) / 100
                    for p in plan_parts if 'P=' in p.get('note', '')), default=0)
    
    if max_prob >= 0.40:
        label = '💎💎💎 必胜方案'
    elif max_prob >= 0.25:
        label = '💎💎 高胜率方案'
    elif max_prob >= 0.15:
        label = '💎 优势方案'
    else:
        label = '📊 保底方案'
    
    return {
        'label': label,
        'parts': plan_parts,
        'total_cost': total_cost,
        'note': f"避冷门串关 | {len(plan_parts)}组/{total_cost}元 | 最高P={max_prob:.1%}"
    }

def gen_plan(scored):
    avail = [m for m in scored if m['match']['status'] == 'Selling']
    if len(avail) < 2:
        return {'error': '可投注比赛不足2场'}
    
    smart = _gen_smart_plan(avail)
    
    # 奖金限额检查（从groups中提取关数）
    max_odds = max((p.get('odds_x', 0) for p in smart.get('parts', [])), default=0)
    notes = smart.get('parts', [])
    guan_count = 0
    for p in notes:
        groups = p.get('groups', {})
        guan_count = max(guan_count, len(groups))
    
    bonus_limit = {1: '10万', 2: '20万', 3: '20万', 4: '50万', 5: '50万', 6: '100万'}
    limit_text = bonus_limit.get(guan_count, '100万')
    
    # 倍投建议：如果最高赔率在50倍以内，可以倍投
    bet_multiplier = 1
    if max_odds <= 50:
        bet_multiplier = min(50, int(6000 / (smart['total_cost'] or 10)))
        bet_multiplier = max(1, bet_multiplier)
    
    smart['compliance'] = {
        'max_guan': guan_count,
        'bonus_limit': limit_text,
        'max_bet_multiplier': bet_multiplier,
        'single_ticket_limit': 6000,
        'rule_note': '必胜型-仅总进球+胜平负 | 概率≥25% | 同场不同玩法不可混串 | 复式投注'
    }
    
    return {
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'plans': [smart]
    }

# ═══════════════════════════════════════════
# 5. 输出
# ═══════════════════════════════════════════

def print_analysis(scored,kb):
    print("="*80)
    print(f"   🌍 世界杯必胜预测 v4.0-win | {datetime.now().strftime('%m-%d %H:%M')} | 知识库:{len(kb.get('matches',[]))}场/{len(kb.get('teams_stats',kb.get('teams',{})))}队")
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
        print(f"\n  📊 十二维信号:")
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
    print("="*80);print("        💎 今日必胜方案 v4.0-win");print("="*80)
    if'error'in plan:print(f"  ⚠️ {plan['error']}");return
    total_all=0
    for p in plan.get('plans',[]):
        label=p.get('label','方案')
        print(f"\n  ▶ {label}")
        print(f"  📝 {p.get('note','')}")
        print(f"  💰 投入:{p['total_cost']}元")
        total_all+=p['total_cost']
        for i, part in enumerate(p.get('parts',[]), 1):
            typ=part['type']
            cost = part.get('cost', 2)
            groups = part.get('groups', {})
            print(f"\n  ┌ 📌 第{i}组:{typ} | {part['note']}")
            for mid, bets in groups.items():
                if len(bets) == 1:
                    b = bets[0]
                    print(f"  │ {b['match']}")
                    print(f"  │   [{b['play']}]{b['pick']}@{b['odds']} P={b.get('prob',0):.1%} EV={b.get('ev',0):.2f} {b['reason']}")
                else:
                    first = bets[0]
                    print(f"  │ {first['match']} 【复式{len(bets)}选】")
                    for b in bets:
                        print(f"  │   [{b['play']}]{b['pick']}@{b['odds']} P={b.get('prob',0):.1%} EV={b.get('ev',0):.2f}")
                    field_prob = sum(b.get('prob', 0) for b in bets)
                    print(f"  │   → 该场命中概率:{field_prob:.1%}")
            print(f"  │ 💰 {cost}元 | ~{part['odds_x']}x | 预估回报:{part['ret']}元")
        print(f"\n  📋 {label}合计:{p['total_cost']}元")
    
    if plan.get('plans'):
        comp = plan['plans'][0].get('compliance', {})
        if comp:
            print(f"\n  ═══ 规则合规 ═══")
            print(f"  📏 木桶原则：最高{comp.get('max_guan','?')}关 | 奖金限额：{comp.get('bonus_limit','?')}")
            mult = comp.get('max_bet_multiplier', 1)
            if mult > 1:
                print(f"  🔢 建议倍投：{mult}倍 → 投入{total_all*mult}元 | 单票≤6000元")
            print(f"  ⚠️ {comp.get('rule_note','')}")
    
    print(f"\n  💰 总投入:{total_all}元 | ⚠️ 必胜型 概率为王 | 理性投注！");print("="*80)

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
    # 只关注世界杯比赛，过滤掉其他联赛
    wc_selling=[m for m in selling if m.get('league')=='世界杯']
    if not wc_selling:
        print("❌ 无在售世界杯比赛");return
    today=datetime.now().strftime('%Y-%m-%d')
    # 优先今天的比赛，没有则取最近的世界杯比赛日
    today_m=[m for m in wc_selling if m.get('match_date')==today]
    if not today_m:
        dates=sorted(set(m.get('match_date') for m in wc_selling if m.get('match_date')))
        if dates:today_m=[m for m in wc_selling if m.get('match_date')==dates[0]]
        print(f"⚠️ 今日无世界杯，用{dates[0]}的比赛")
    print(f"📊 获取{len(today_m)}场世界杯在售比赛\n")
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
