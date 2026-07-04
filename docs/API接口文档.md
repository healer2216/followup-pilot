# FollowUp Pilot API 接口文档

## 一、基础信息

**Base URL**: `http://localhost:8080`  
**Content-Type**: `application/json`  
**认证方式**: 无（演示版本）  
**CORS**: 已启用，允许所有来源

---

## 二、接口清单

| 方法 | 路径 | 功能 | 状态 | 说明 |
|-----|------|------|------|------|
| GET | `/` | 首页（返回前端页面） | ✅ 已实现 | 返回 HTML 页面 |
| GET | `/api/health` | 健康检查 | ✅ 已实现 | 服务状态检测 |
| POST | `/api/parse` | 解析出院小结 | ✅ 已实现 | LLM 结构化提取 |
| POST | `/api/plan` | 生成随访计划 | ⚠️ Mock | 返回模拟数据 |
| POST | `/api/chat` | 对话随访 | ✅ 已实现 | 实时 AI 对话 |
| GET | `/api/sessions/{id}` | 获取会话信息 | ✅ 已实现 | 查询历史会话 |

---

## 三、接口详情

### 3.1 健康检查

#### 请求
```
GET /api/health
```

#### 响应
**Status Code**: 200 OK

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

#### 说明
- 用于检测服务是否正常运行
- 返回当前 API 版本号

---

### 3.2 解析出院小结

#### 请求
```
POST /api/parse
Content-Type: application/json

{
  "text": "患者张三，男，65岁。诊断：2型糖尿病、高血压3级。用药：二甲双胍 500mg bid..."
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| text | string | 是 | 出院小结文本内容 |

#### 成功响应
**Status Code**: 200 OK

```json
{
  "success": true,
  "data": {
    "parsed": {
      "patient_name": "张三",
      "gender": "男",
      "age": 65,
      "admission_date": null,
      "discharge_date": null,
      "diagnoses": ["2型糖尿病", "高血压3级"],
      "medications": [
        {
          "name": "二甲双胍",
          "dosage": "500mg",
          "frequency": "每日两次",
          "timing": "餐后"
        },
        {
          "name": "氨氯地平",
          "dosage": "5mg",
          "frequency": "每日一次",
          "timing": "晨起"
        }
      ],
      "vital_signs": [
        {
          "name": "空腹血糖",
          "value": "7.8",
          "unit": "mmol/L",
          "reference_range": "4.4-7.0",
          "status": "high"
        },
        {
          "name": "血压",
          "value": "145/92",
          "unit": "mmHg",
          "reference_range": "<140/90",
          "status": "high"
        }
      ],
      "chief_complaint": "",
      "treatment_summary": "",
      "discharge_instructions": "",
      "confidence": 0.92
    },
    "risk_profile": {
      "overall_risk": "medium",
      "risk_factors": [
        "老年患者(65岁)，药物代谢减慢",
        "多药联用(3种)，注意药物相互作用",
        "共病风险：糖尿病+高血压，心血管事件风险增加"
      ],
      "special_attention": [
        "跌倒预防",
        "定期药物审查",
        "同时监测血糖和血压"
      ],
      "drug_interactions": [
        "未发现高风险药物组合，但建议定期审查多药联用方案"
      ]
    },
    "evidence_stats": {
      "search_queries": 0,
      "total_results": 0,
      "after_rerank": 0,
      "cited": 0
    }
  }
}
```

#### 失败响应
**Status Code**: 200 OK

```json
{
  "success": false,
  "error": "请输入出院小结文本"
}
```

#### 性能指标
- **LLM 调用耗时**：5-8 秒
- **总耗时**：6-10 秒（含网络传输）
- **置信度范围**：0.0 - 1.0

#### 字段说明

**parsed 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| patient_name | string | 患者姓名 |
| gender | string | 性别（男/女） |
| age | integer | 年龄 |
| admission_date | string/null | 入院日期（YYYY-MM-DD） |
| discharge_date | string/null | 出院日期（YYYY-MM-DD） |
| diagnoses | array[string] | 诊断列表 |
| medications | array[object] | 用药方案列表 |
| vital_signs | array[object] | 检验指标列表 |
| confidence | float | 解析置信度 |

**medication 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| name | string | 药物名称 |
| dosage | string | 剂量 |
| frequency | string | 频次 |
| timing | string | 服用时间 |

**vital_sign 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| name | string | 指标名称 |
| value | string | 数值（可以是复合值如"145/92"） |
| unit | string | 单位 |
| reference_range | string | 参考范围 |
| status | string | 状态（normal/high/low） |

**risk_profile 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| overall_risk | string | 整体风险等级（low/medium/high） |
| risk_factors | array[string] | 风险因素列表 |
| special_attention | array[string] | 特殊注意事项 |
| drug_interactions | array[string] | 药物相互作用警告 |

---

### 3.3 生成随访计划

#### 请求
```
POST /api/plan
Content-Type: application/json

{
  "summary_text": "患者张三，男，65岁。诊断：2型糖尿病...",
  "session_id": "session_001"
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| summary_text | string | 是 | 出院小结文本 |
| session_id | string | 否 | 会话ID（用于关联） |

#### 成功响应（当前为 Mock 数据）
**Status Code**: 200 OK

```json
{
  "success": true,
  "data": {
    "evidence_stats": {
      "search_queries": 6,
      "total_results": 35,
      "after_rerank": 8,
      "cited": 5
    },
    "generated_at": "2026-07-01",
    "timeline": [
      {
        "day_number": 1,
        "date": "2026-06-28",
        "label": "出院第 1 天",
        "icon": "sunrise",
        "color": "medical",
        "tasks": [
          {
            "task_type": "medication",
            "title": "按时服药",
            "description": "二甲双胍 500mg 早晚餐后各一次\n氨氯地平 5mg 晨起一次\n阿托伐他汀 20mg 睡前一次",
            "icon": "pill",
            "color": "blue",
            "evidence_refs": ["盐酸二甲双胍片说明书"],
            "evidence_grades": ["E"]
          },
          {
            "task_type": "monitoring",
            "title": "监测指标",
            "description": "空腹血糖 + 餐后2h血糖\n血压（晨起 + 睡前）\n目标: 空腹 4.4-7.0 mmol/L",
            "icon": "activity",
            "color": "emerald",
            "evidence_refs": ["中国2型糖尿病防治指南(2020)"],
            "evidence_grades": ["A"]
          },
          {
            "task_type": "diet",
            "title": "饮食管理",
            "description": "低盐低脂饮食\n控制碳水摄入，少食多餐\n避免高糖饮料和精制食品",
            "icon": "utensils",
            "color": "amber",
            "evidence_refs": ["高血压患者饮食管理指南"],
            "evidence_grades": ["A"]
          }
        ]
      },
      {
        "day_number": 3,
        "date": "2026-06-30",
        "label": "出院第 3 天",
        "icon": "stethoscope",
        "color": "emerald",
        "tasks": [
          {
            "task_type": "checkup",
            "title": "症状自查",
            "description": "注意有无低血糖症状：心慌、出汗、手抖\n注意有无体位性低血压：起身头晕",
            "icon": "alert-triangle",
            "color": "rose",
            "evidence_refs": ["老年糖尿病患者低血糖风险研究"],
            "evidence_grades": ["C"]
          },
          {
            "task_type": "activity",
            "title": "活动建议",
            "description": "餐后30分钟散步15-20分钟\n避免剧烈运动，注意防跌倒\n运动前后监测血糖",
            "icon": "footprints",
            "color": "violet",
            "evidence_refs": ["糖尿病运动管理RCT研究"],
            "evidence_grades": ["B"]
          }
        ]
      },
      {
        "day_number": 7,
        "date": "2026-07-04",
        "label": "出院第 1 周",
        "icon": "calendar",
        "color": "amber",
        "tasks": [
          {
            "task_type": "review",
            "title": "一周回顾",
            "description": "回顾本周血糖/血压记录，评估药物耐受情况\n如出现持续头晕、心悸，请联系随访助手或提前就诊",
            "icon": "clipboard-check",
            "color": "cyan",
            "evidence_refs": ["中国2型糖尿病防治指南(2020)"],
            "evidence_grades": ["A"]
          }
        ]
      },
      {
        "day_number": 14,
        "date": "2026-07-11",
        "label": "出院第 2 周 — 门诊复查",
        "icon": "hospital",
        "color": "medical",
        "tasks": [
          {
            "task_type": "checkup",
            "title": "内分泌科门诊复查",
            "description": "复查项目：糖化血红蛋白(HbA1c)、肝肾功能、血脂\n评估药物疗效，必要时调整方案",
            "icon": "stethoscope",
            "color": "medical",
            "evidence_refs": ["出院后2-4周建议首次门诊随访 — 中国2型糖尿病防治指南"],
            "evidence_grades": ["A"]
          }
        ]
      }
    ]
  }
}
```

#### 待实现功能
- ✅ 真实 RAG Pipeline 集成
- ✅ 多 Agent 编排器（Triage -> Search -> Plan -> Review）
- ✅ 证据分级引擎
- ✅ 审核员评分

#### 字段说明

**timeline 数组**
| 字段 | 类型 | 说明 |
|-----|------|------|
| day_number | integer | 第几天（从出院日算起） |
| date | string | 具体日期（YYYY-MM-DD） |
| label | string | 展示标签（如"出院第 1 天"） |
| icon | string | 图标名称（Lucide Icons） |
| color | string | 颜色主题 |
| tasks | array[object] | 当天任务列表 |

**task 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| task_type | string | 任务类型（medication/monitoring/diet/activity/checkup/review） |
| title | string | 任务标题 |
| description | string | 详细描述（支持换行符） |
| icon | string | 图标名称 |
| color | string | 颜色主题 |
| evidence_refs | array[string] | 引用的证据标题列表 |
| evidence_grades | array[string] | 对应证据分级（A/B/C/D/E） |

**evidence_stats 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| search_queries | integer | 检索查询次数 |
| total_results | integer | 检索结果总数 |
| after_rerank | integer | 重排序后保留数量 |
| cited | integer | 实际引用数量 |

---

### 3.4 对话随访

#### 请求
```
POST /api/chat
Content-Type: application/json

{
  "session_id": "test_001",
  "message": "今天空腹血糖6.5"
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| session_id | string | 否 | 会话ID（默认"default"） |
| message | string | 是 | 用户消息 |

#### 成功响应
**Status Code**: 200 OK

```json
{
  "success": true,
  "data": {
    "reply": "你坚持监测血糖的习惯真的特别好，这是管理病情非常关键的一步哦~\n\n正常成人的空腹血糖参考范围是3.9~6.1mmol/L，你这次的测量值6.5mmol/L比正常上限稍高，目前属于轻度升高的状态。\n\n建议你注意以下几点：\n1. 饮食控制：减少精制米面、高糖零食的摄入\n2. 适当运动：每天保持30分钟左右的温和运动\n3. 继续监测：建议连续3天记录空腹血糖\n\n如果连续3天空腹血糖都高于7.0mmol/L，建议提前到门诊复查。",
    "alert_level": "yellow",
    "alert_detail": "fasting_glucose = 6.5 mmol/L，需要关注",
    "evidence_refs": [
      {
        "text": "中国2型糖尿病防治指南(2020): 空腹血糖控制目标 4.4-7.0 mmol/L"
      }
    ],
    "suggest_actions": [
      "继续监测空腹血糖",
      "注意饮食控制",
      "如持续偏高请联系医生"
    ],
    "vital_records": [
      {"date": "Day1", "type": "空腹血糖", "value": 7.2},
      {"date": "Day2", "type": "空腹血糖", "value": 7.0},
      {"date": "Day3", "type": "空腹血糖", "value": 6.8}
    ]
  }
}
```

#### 响应字段说明
| 字段 | 类型 | 说明 |
|-----|------|------|
| reply | string | AI 生成的回复内容（支持 Markdown 格式） |
| alert_level | string | 预警等级：green/yellow/red |
| alert_detail | string | 预警详细信息 |
| evidence_refs | array[object] | 引用的循证证据列表 |
| suggest_actions | array[string] | 建议行动项 |
| vital_records | array[object] | 历史指标记录 |

**evidence_ref 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| text | string | 证据描述文本 |

**vital_record 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| date | string | 记录日期 |
| type | string | 指标类型 |
| value | number | 指标数值 |

#### 预警等级说明
- **green**：指标在正常范围内，无需特别关注
- **yellow**：指标略超阈值，需要关注和监测
- **red**：指标严重超标或出现危险症状，需紧急处理

#### 性能指标
- **第一次 LLM 调用**（提取数值）：2-3 秒
- **第二次 LLM 调用**（生成回复）：8-10 秒
- **总耗时**：10-13 秒

#### 错误处理
如果 LLM 调用失败，系统会回退到 Mock 回复（固定模板）。

#### 示例场景

**场景 1：正常血糖**
```json
{
  "message": "今天空腹血糖5.8"
}
// 返回 alert_level: "green"
```

**场景 2：轻度升高**
```json
{
  "message": "今天空腹血糖8.5"
}
// 返回 alert_level: "yellow"
```

**场景 3：严重超标**
```json
{
  "message": "今天空腹血糖18.2"
}
// 返回 alert_level: "red"
```

**场景 4：低血糖症状**
```json
{
  "message": "感觉心慌、出汗、手抖"
}
// 返回 alert_level: "yellow"，建议立即进食糖果
```

**场景 5：血压异常**
```json
{
  "message": "血压150/95"
}
// 返回 alert_level: "yellow"，建议减少盐分摄入
```

---

### 3.5 获取会话信息

#### 请求
```
GET /api/sessions/{session_id}
```

#### 路径参数
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| session_id | string | 是 | 会话ID |

#### 成功响应
**Status Code**: 200 OK

```json
{
  "success": true,
  "data": {
    "session_id": "test_001",
    "patient_id": "patient_001",
    "created_at": "2026-07-02T10:30:00",
    "messages": [
      {
        "role": "user",
        "content": "今天空腹血糖6.5",
        "timestamp": "2026-07-02T10:30:00",
        "alert_level": "yellow",
        "evidence_refs": []
      },
      {
        "role": "assistant",
        "content": "你坚持监测血糖的习惯真的特别好...",
        "timestamp": "2026-07-02T10:30:12",
        "alert_level": "yellow",
        "evidence_refs": ["中国2型糖尿病防治指南(2020)"]
      }
    ],
    "current_alert": "yellow",
    "vital_records": [
      {"date": "Day1", "type": "空腹血糖", "value": 7.2},
      {"date": "Day2", "type": "空腹血糖", "value": 7.0},
      {"date": "Day3", "type": "空腹血糖", "value": 6.8}
    ]
  }
}
```

#### 失败响应
**Status Code**: 200 OK

```json
{
  "success": false,
  "error": "会话不存在"
}
```

#### 字段说明

**message 对象**
| 字段 | 类型 | 说明 |
|-----|------|------|
| role | string | 角色（user/assistant/system） |
| content | string | 消息内容 |
| timestamp | string | 时间戳（ISO 8601 格式） |
| alert_level | string/null | 预警等级（仅 assistant 消息） |
| evidence_refs | array[string] | 引用证据列表 |

---

## 四、错误码说明

| 错误码 | 说明 | 处理方式 |
|-------|------|---------|
| 200 | 成功 | 正常处理响应数据 |
| 400 | 请求参数错误 | 检查请求参数格式 |
| 404 | 资源不存在 | 检查 URL 路径 |
| 500 | 服务器内部错误 | 联系技术支持 |

---

## 五、最佳实践

### 5.1 会话管理
- 使用唯一的 `session_id` 标识每个患者的会话
- 建议在客户端使用 UUID 生成 session_id
- 会话数据存储在内存中，重启服务后会丢失

### 5.2 错误处理
- 始终检查响应中的 `success` 字段
- 当 `success` 为 `false` 时，读取 `error` 字段获取错误信息
- 实现重试机制应对 LLM 调用超时

### 5.3 性能优化
- 对于相同的出院小结文本，可以考虑客户端缓存解析结果
- 对话随访响应时间较长（10-13秒），建议前端显示加载动画
- 避免频繁调用 `/api/parse`，该接口耗时较长

### 5.4 安全建议
- 生产环境应启用 HTTPS
- 添加 API 认证机制（如 JWT Token）
- 实现速率限制防止滥用
- 对患者数据进行加密存储

---

## 六、更新日志

### v1.0 (2026-07-02)
- ✅ 初始版本发布
- ✅ 实现出院小结解析接口
- ✅ 实现对话随访接口
- ✅ 实现会话管理接口
- ⚠️ 随访计划接口返回 Mock 数据

---

**文档版本**: v1.0  
**最后更新**: 2026-07-02  
**维护者**: FollowUp Pilot 开发团队
