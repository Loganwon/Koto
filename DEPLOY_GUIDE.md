# Koto SaaS 部署指南

## 架构概览

```
用户浏览器
    ↓
  / (Landing Page - 注册/登录)
    ↓ 认证后
  /app (主应用 - 聊天、文档、PPT...)
    ↓
  Flask API (160+ 路由)
    ↓
  Gemini API / Ollama 本地模型
```

## 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp config/gemini_config.env.example config/gemini_config.env
# 编辑 config/gemini_config.env 填入你的 GEMINI_API_KEY

# 3. 本地运行（桌面模式，带 pywebview 窗口）
python koto_app.py

# 4. 本地运行（纯 Web 模式，无桌面窗口）
python server.py
# 访问 http://localhost:5000
```

## Docker 部署

```bash
# 构建镜像
docker build -t koto .

# 运行容器
docker run -p 5000:5000 \
  -e GEMINI_API_KEY=your_api_key \
  -e KOTO_AUTH_ENABLED=true \
  -e KOTO_JWT_SECRET=$(openssl rand -hex 32) \
  -e KOTO_DEPLOY_MODE=cloud \
  koto

# 访问 http://localhost:5000
```

## Railway 部署（推荐）

### 首次部署

1. **推送代码到 GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial Koto SaaS"
   git remote add origin https://github.com/YOUR_USER/koto.git
   git push -u origin main
   ```

2. **连接 Railway**
   - 访问 [railway.app](https://railway.app)
   - 创建新项目 → 从 GitHub 导入
   - 选择你的 Koto 仓库

3. **配置环境变量**
   在 Railway 的 Variables 面板中添加：
   | 变量名 | 值 | 说明 |
   |--------|-----|------|
   | `GEMINI_API_KEY` | `your_key` | Google AI API 密钥 |
   | `KOTO_AUTH_ENABLED` | `true` | 启用用户认证 |
   | `KOTO_JWT_SECRET` | 随机 64 位 hex | JWT 签名密钥 |
   | `KOTO_DEPLOY_MODE` | `cloud` | 云部署模式 |
   | `KOTO_MAX_DAILY_REQUESTS` | `100` | 每用户每日限额 |

4. **部署**
   - Railway 会自动检测 `Dockerfile` 并构建
   - 部署完成后获得公网 URL（如 `koto-production.up.railway.app`）

### 自动更新

每次 `git push` 到 main 分支，Railway 会自动重新构建和部署。不需要手动打包。

```bash
# 更新后只需
git add .
git commit -m "New feature: ..."
git push
# Railway 自动部署 ✅
```

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GEMINI_API_KEY` | (必填) | Google Gemini API 密钥 |
| `KOTO_PORT` | `5000` | 服务端口 |
| `KOTO_AUTH_ENABLED` | `false` | 启用认证系统 |
| `KOTO_JWT_SECRET` | 随机生成 | JWT 签名密钥（生产环境必须固定） |
| `KOTO_JWT_EXPIRY_HOURS` | `72` | Token 过期时间（小时） |
| `KOTO_DEPLOY_MODE` | `local` | 部署模式 (`local` / `cloud`) |
| `KOTO_MAX_DAILY_REQUESTS` | `100` | 每用户每日 API 调用限额 |
| `KOTO_CORS_ORIGINS` | `*` | CORS 允许的来源 |
| `KOTO_SITE_URL` | (空) | 站点 URL（云模式 CORS 用） |
| `KOTO_DEBUG` | `false` | 调试模式 |
| `KOTO_ADMIN_TOKEN` | (空) | 管理员 API Token |

## 本地 vs 云模式区别

| 特性 | 本地模式 | 云模式 |
|------|---------|--------|
| 首页 | 直接进入聊天 | Landing Page |
| 认证 | 不需要 | 注册/登录 |
| CORS | 允许所有 | 限制来源 |
| Debug | 可开启 | 关闭 |
| Desktop | pywebview 窗口 | 纯浏览器 |
| 文件系统 | 完整访问 | 容器内沙箱 |

## 安全注意事项

- 生产环境必须设置 `KOTO_JWT_SECRET` 为固定值
- 不要将 `config/gemini_config.env` 提交到 Git（已在 .gitignore 中排除）
- `KOTO_DEBUG=false` 在生产环境
- 设置合理的 `KOTO_MAX_DAILY_REQUESTS` 防止滥用
