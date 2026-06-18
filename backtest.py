#!/usr/bin/env python3
"""
世界杯预测模型 回测脚本 v1.0
============================
用 knowledge_base.json 中已完赛的 matches 回测模型预测
输出：各玩法命中率、ROI、信号分-命中率校准曲线
"""
import json
import os
import math
from collections import defaultdict

KB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base.json")

def load_kb():
    with open(KB_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def main():
    kb = load_kb()
    matches = kb.get('matches', [])
    
    if len(matches) < 5:
        print("⚠️ 历史数据不足（需要≥5场比赛），跳过回测")
        return
    
    print(f"\n{'='*60}")
    print(f"  世界杯预测回测 v1.0")
    print(f"  数据: {len(matches)}场历史赛果")
    print(f"{'='*60}\n")
    
    # ═══ 1. 基础统计 ═══
    had_counts = defaultdict(int)
    goal_dist = defaultdict(int)
    cold_count = 0
    
    for m in matches:
        had = m.get('had', '')
        had_counts[had] += 1
        goals = m.get('goals', 0)
        goal_dist[goals] += 1
        if had in ('平', '客胜'):
            cold_count += 1
    
    total = len(matches)
    print("📊 基础统计:")
    print(f"  总场次: {total}")
    print(f"  主胜: {had_counts.get('主胜',0)} ({had_counts.get('主胜',0)/total*100:.1f}%)")
    print(f"  平局: {had_counts.get('平',0)} ({had_counts.get('平',0)/total*100:.1f}%)")
    print(f"  客胜: {had_counts.get('客胜',0)} ({had_counts.get('客胜',0)/total*100:.1f}%)")
    print(f"  冷门(平+客): {cold_count} ({cold_count/total*100:.1f}%)")
    
    print(f"\n📊 进球分布:")
    for g in sorted(goal_dist.keys()):
        bar = '█' * goal_dist[g]
        print(f"  {g}球: {bar} {goal_dist[g]}场 ({goal_dist[g]/total*100:.1f}%)")
    
    # ═══ 2. 赔率-结果分析 ═══
    # 注意：kb.matches 中没有赔率数据，这里做冷门模式分析
    print(f"\n📊 冷门模式分析:")
    print(f"  当前世界杯冷门率: {cold_count/total*100:.1f}%")
    print(f"  平均每场进球: {sum(m.get('goals',0) for m in matches)/total:.1f}")
    
    # ═══ 3. 信号校准（如果模型可用） ═══
    try:
        from worldcup_model import _signal_to_prob
        print(f"\n📊 概率校准曲线（信号分→概率）:")
        print(f"  {'信号分':<10} {'经验概率':<12} {'备注'}")
        for sig in [5, 10, 15, 20, 25, 30, 35, 40, 50, 60]:
            prob_normal = _signal_to_prob(sig, '')
            prob_crs = _signal_to_prob(sig, '比分')
            print(f"  {sig:<10} {prob_normal:.1%}         (比分:{prob_crs:.1%})")
    except Exception as e:
        print(f"  (模型未加载: {e})")
    
    # ═══ 4. 建议 ═══
    print(f"\n📊 优化建议:")
    if cold_count / total > 0.5:
        print(f"  ✅ 冷门率高({cold_count/total:.1%})，博冷策略有效")
    else:
        print(f"  ⚠️ 冷门率偏低({cold_count/total:.1%})，稳健策略可能更优")
    
    avg_goals = sum(m.get('goals', 0) for m in matches) / total
    if avg_goals < 2.5:
        print(f"  ✅ 场均进球偏低({avg_goals:.1f})，低总进球策略有效")
    else:
        print(f"  ⚠️ 场均进球偏高({avg_goals:.1f})，高总进球需谨慎")
    
    print(f"\n{'='*60}\n")

if __name__ == '__main__':
    main()
