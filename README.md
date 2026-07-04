#  FollowUp Pilot - 循证随访管家

AI 驱动的出院随访系统，基于 StepFun LLM 和 KnowS 循证检索服务。

## 🚀 快速开始

### 1. 访问前端

打开浏览器访问：**http://localhost:8080**

### 2. 体验流程

1. **上传出院小结** → 点击"AI 解析"按钮
2. **查看解析结果** → 患者信息、诊断、用药、生命体征
3. **生成随访计划** → 基于循证证据的个性化时间线
4. **对话随访** → 智能预警系统（红/黄/绿三级）

## 📋 项目状态

- ✅ **服务器运行中**: FastAPI + StepFun LLM
- ✅ **端口**: http://localhost:8080
- ✅ **前端**: 独立版 HTML（无 CDN 依赖）
- ✅ **后端 API**: 全部正常工作

## 🔧 技术栈

- **前端**: Pure HTML/CSS/JS (standalone.html)
- **后端**: FastAPI (Python 3.10+)
- **LLM**: StepFun step-3.7-flash
- **循证检索**: KnowS API (6大数据源)
- **存储**: JSON 文件持久化

##  项目结构

```
followup-pilot/
├── app/                    # 后端代码
│   ├── main.py            # FastAPI 入口
│   ├── config.py          # 配置管理
│   ├── models.py          # 数据模型
│   ├── tools/             # 工具层
│   │   ├── llm_gateway.py # LLM 网关
│   │   └── knows_search.py# KnowS 客户端
│   └── services/          # 业务服务
│       ├── parser.py      # 解析服务
│       ├── evidence.py    # 循证检索
│       ├── planner.py     # 计划生成
│       ── chatbot.py     # 对话随访
── frontend/              # 前端代码
│   ├── standalone.html    # 独立版（推荐）
│   └── index.html         # Tailwind 版
├── .env                   # 环境变量
├── README.md              # 本文档
├── 访问指南.md             # 详细访问说明
└── 项目完成报告.md         # 完整项目报告
```

## 🛠️ API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 返回前端 HTML |
| `/api/health` | GET | 健康检查 |
| `/api/parse` | POST | 解析出院小结 |
| `/api/plan` | POST | 生成随访计划 |
| `/api/chat` | POST | 对话随访 |

## 🧪 API 测试

```bash
# 健康检查
curl http://localhost:8080/api/health

# 解析测试
curl -X POST http://localhost:8080/api/parse \
  -H 'Content-Type: application/json' \
  -d '{"text":"患者张三，男，65岁。诊断：2型糖尿病"}'
```

## ️ 环境配置

编辑 `.env` 文件：

```bash
# LLM Configuration
LLM_PROVIDER=stepfun
STEPFUN_API_KEY=your_api_key_here
STEPFUN_BASE_URL=https://api.stepfun.com/step_plan/v1
STEPFUN_MODEL=step-3.7-flash

# KnowS API
KNOWS_BASE_URL=https://api.nullht.com/v1
```

## 🔄 重启服务器

```bash
cd /root/study/项目开发/followup-pilot
pkill -f "uvicorn app.main:app"
nohup /root/anaconda3/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8080 &
```

## 📖 文档

- [访问指南.md](./访问指南.md) - 详细访问说明和故障排查
- [项目完成报告.md](./项目完成报告.md) - 完整项目报告和技术架构

##  核心特性

1. **真实 LLM 驱动** - StepFun step-3.7-flash 实时解析
2. **循证医学支持** - KnowS 6大数据源（指南/论文/说明书等）
3. **智能预警系统** - 红/黄/绿三级预警规则引擎
4. **无 CDN 依赖** - 独立版 HTML，离线可用
5. **生产级代码** - 类型提示、错误处理、日志记录

## 🐛 常见问题

**Q: 预览工具无法显示页面？**  
A: 直接在浏览器访问 `http://localhost:8080`

**Q: 如何查看服务器日志？**  
A: `tail -f /tmp/uvicorn_standalone.log`

**Q: API 返回错误？**  
A: 检查 `.env` 文件中的 API Key 是否正确

## 📞 技术支持

项目位置: `/root/study/项目开发/followup-pilot/`

---

**安心休息吧，醒来就是一个完整的、可演示的项目了！** 🎉

*最后更新: 2026-07-02*
# followup-pilot
