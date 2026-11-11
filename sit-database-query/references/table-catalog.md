# SIT 库表清单

快照时间 2026-10-30（MySQL 5.7.44）。表可能增减，实际以 `--list-tables` / `--find` 为准。

## citytsm_pm — 项目管理

| 表 | 说明 |
| --- | --- |
| attach_file | 上传文件记录表 |
| biz_config | 字典表 |
| biz_config_copy1 | 字典表（备份） |
| city | 城市 |
| city_board | 城市管理 |
| commission_base_config | 基础信息配置 |
| commission_product_coefficient | 业务系数 |
| commission_product_config | 业务配置 |
| commission_product_summary | 业务提成明细 |
| commission_project_summary | 项目明细 |
| commission_reward | 激励 |
| commission_reward_summary | 提成奖金发放明细 |
| commission_user_config | 人员配置 |
| contract | 合同管理 |
| cooperator | 合作公司 |
| coop_city | 重点城市 |
| coop_city_record | 重点城市动态 |
| coop_city_score | 城市打分 |
| coop_staff | 公司员工 |
| dwd_trans_info_32020002 | 交易结算表（74 万+） |
| expense | 报销单 |
| expense_cost_record | 报销成本明细 |
| expense_product | 费用归属 |
| expense_record | 报销费用明细 |
| fund | 资金管理 |
| fund_bd | 资金 BD 关联表 |
| fund_record | 资金流水 |
| global_config | 组件配置信息表 |
| job_detail | 定时任务详情表 |
| kpi_config | 绩效分配 |
| kpi_record | 考核记录表 |
| mail_content | 邮件详情 |
| mail_contract_scan | 合同扫描件邮件内容 |
| mail_info | 邮件 |
| mail_template | 邮件模板 |
| open_sync_biz_data | 高优先级数据 |
| open_sync_biz_data_medium | 中低优先级数据 |
| product | 业务管理 |
| product_qa | 业务答疑 |
| product_record | 业务动态 |
| product_target | 业务指标 |
| project | 项目管理 |
| project_copy1 | 项目管理（备份） |
| project_record | 项目管理 |
| project_sign | 已签项目 |
| project_tag | 标签管理 |
| qa_cat_business | cat 事件 |
| qa_cat_event | cat 事件 |
| qa_cat_exclude | cat 事件 |
| qa_cat_feedback | cat 事件 |
| qa_deploy_info | 项目部署信息 |
| qa_deploy_info_copy1 | 项目部署信息（备份） |
| qa_issue_report | 客服工单表 |
| qa_project_record | 项目发布记录 |
| qa_project_record_copy1 | 项目发布记录（备份） |
| qa_service_dict | 服务名白名单 |
| qa_source_type | 环境类型定义 |
| qa_version_no | cat 事件 |
| quote_apply | 报价申请 |
| quote_config | 报价配置 |
| quote_record | 报价记录 |
| receive_payment | 收付款管理 |
| stage | 业务流程 |
| stage_template | 业务流程模板 |
| survey_record | 调研记录 |
| survey_template | 调研模板 |
| sys_config | 参数配置表 |
| sys_dept | 部门表 |
| sys_dict_data | 字典数据表 |
| sys_dict_data_copy1 | 字典数据表（备份） |
| sys_dict_type | 字典类型表 |
| sys_job | 定时任务调度表 |
| sys_job_log | 定时任务调度日志表 |
| sys_logininfor | 系统访问记录 |
| sys_menu | 菜单权限表 |
| sys_notice | 通知公告表 |
| sys_oper_log | 操作日志记录 |
| sys_post | 岗位信息表 |
| sys_role | 角色信息表 |
| sys_role_dept | 角色和部门关联表 |
| sys_role_menu | 角色和菜单关联表 |
| sys_user | 用户信息表 |
| sys_user_auth_data | 用户数据权限表 |
| sys_user_online | 在线用户记录 |
| sys_user_post | 用户与岗位关联表 |
| sys_user_role | 用户和角色关联表 |
| user_city | 城市 BD 关联表 |
| user_city_product | 城市业务人员配置 |
| yy_chuzhi_report | 运营储值月报表 |
| yy_coop_rule | 结算规则 |
| yy_data_record | 运营数据维护 |
| yy_day_report | 运营结算日报表 |
| yy_month_report | 运营结算月报表 |
| yy_project | 运营项目明细 |
| yy_project_rule | 结算规则 |
| yy_project_rule_record | 计费配置列表 |
| yy_rule_detail | 结算规则详情 |

## sit_op_equities_manager — 权益中心

| 表 | 说明 |
| --- | --- |
| benefit | 权益池 |
| benefit_check_batch | 对账记录表 |
| benefit_config | 权益配置表 |
| benefit_prize | 权益奖品关联表 |
| benefit_record | 用户权益记录表（17 万+） |
| benefit_record_fail | 权益发放失败表 |
| benefit_record_used | 权益核销明细 |
| benefit_rule | 权益规则 |
| lucky_draw_record | 抽奖记录表（13 万+） |
| prize | 奖品表 |
| prize_group | 奖品组合表 |
| qingdao_check_detail | 青岛对账明细 |
| qingdao_check_mistake | 差异账 |
| wechat_merchant_config | 微信商户配置 |

## sit_citytsm_cloud — 云枢平台

| 表 | 说明 |
| --- | --- |
| agent_config | 智能体配置表 |
| infra_api_access_log | API 访问日志表（180 万+） |
| infra_api_error_log | 系统异常日志 |
| infra_codegen_column | 代码生成字段定义 |
| infra_codegen_table | 代码生成表定义 |
| infra_config | 参数配置表 |
| infra_data_source_config | 数据源配置表 |
| infra_file | 文件表 |
| infra_file_config | 文件配置表 |
| infra_file_content | 文件表 |
| infra_job | 定时任务表 |
| infra_job_log | 定时任务日志表 |
| system_dept | 部门表 |
| system_dict_data | 字典数据表 |
| system_dict_type | 字典类型表 |
| system_login_log | 系统访问记录 |
| system_mail_account | 邮箱账号表 |
| system_mail_log | 邮件日志表 |
| system_mail_template | 邮件模版表 |
| system_menu | 菜单权限表 |
| system_menu_apply_blacklist | 菜单申请黑名单 |
| system_menu_apply_record | 菜单申请记录 |
| system_microapp | 微应用管理 |
| system_notice | 通知公告表 |
| system_notify_message | 站内信消息表 |
| system_notify_template | 站内信模板表 |
| system_oauth2_access_token | OAuth2 访问令牌（72 万+） |
| system_oauth2_approve | OAuth2 批准表 |
| system_oauth2_client | OAuth2 客户端表 |
| system_oauth2_code | OAuth2 授权码表 |
| system_oauth2_refresh_token | OAuth2 刷新令牌 |
| system_operate_log | 操作日志记录 V2 |
| system_post | 岗位信息表 |
| system_role | 角色信息表 |
| system_role_menu | 角色和菜单关联表 |
| system_sms_channel | 短信渠道 |
| system_sms_code | 手机验证码 |
| system_sms_log | 短信日志 |
| system_sms_template | 短信模板 |
| system_social_client | 社交客户端表 |
| system_social_user | 社交用户表 |
| system_social_user_bind | 社交绑定表 |
| system_tenant | 租户表 |
| system_tenant_authorization | 租户免密访问授权表 |
| system_tenant_package | 租户套餐表 |
| system_users | 用户信息表 |
| system_user_affiliation | 用户和租户关联表 |
| system_user_join_application | 用户加入组织申请 |
| system_user_post | 用户岗位表 |
| system_user_role | 用户和角色关联表 |
| transport_line | 公交地铁线路表 |
| transport_station | 公交地铁站点表 |
| transport_station_facility | 站点设施表 |
