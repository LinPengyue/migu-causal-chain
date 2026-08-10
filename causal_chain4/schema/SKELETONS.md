# causal_chain4 业务因果链骨架速查
#
# 完整定义见 schema/skeletons.py；本文件仅作长度与模版一览。
#
# | template_id | 中文 | 建议长度 |
# |---|---|---|
# | individual_breakthrough_goal | 个人突破后射门进球链 | 3-8 |
# | team_buildup_goal | 团队配合射门进球链 | 3-10 |
# | corner_coop_goal | 角球配合进球链 | 3-9 |
# | corner_cross_goal | 角球传中进球链 | 3-8 |
# | turnover_counter_goal | 抢断/反击/失误造成进球链 | 3-9 |
# | shot_save_chain | 射门扑救链 | 2-10（允许组织前缀） |
# | goal_line_extreme_save_chain | 门线极限救险链 | 2-10 |
# | throw_in_build_up_chain | 手抛球发动进攻链 | 2-8 |
# | outcome_other | 其他（兜底） | 2-10 |
#
# 规则模式 rules_mode=annotation：白名单内事件可相邻；soft_match 看结局+关键节点+骨架覆盖。
