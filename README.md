# gzlib-shelf-finder

广州图书馆馆藏位置查询工具。项目采用 **原生前端 + Python 标准库 HTTP 服务 + SQLite 本地缓存**，不依赖 Flask / FastAPI 等额外后端框架。

## 现在这个版本做了什么整理

- 清理了 `.git`、`__pycache__`、`.DS_Store`、本地缓存数据库
- 保留了最小可运行目录，适合单独放进一个文件夹直接部署
- 增加了 `setup.sh` 和 `start.sh`
- 增加了 `/api/health` 健康检查接口
- 当上游馆别列表或推荐书单暂时不可访问时，页面仍可启动，不会因为初始化失败直接崩掉

## 目录结构

- `index.html`：页面结构
- `styles.css`：页面样式
- `app.js`：前端交互
- `server.py`：后端服务、缓存、查询逻辑
- `setup.sh`：初始化虚拟环境并安装依赖
- `start.sh`：启动服务
- `data/`：运行时缓存目录

## 本地运行

```bash
cd gzlib-shelf-finder-final
./setup.sh
./start.sh
```

浏览器打开：

```text
http://127.0.0.1:8011
```

## 也可以手动运行

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

## 环境变量

- `PORT`：服务端口，默认 `8011`
- `HOST`：监听地址，默认 `0.0.0.0`
- `GZLIB_PROXY_POOL`：可选代理池，多个代理用逗号或换行分隔

示例：

```bash
export PORT=8011
export GZLIB_PROXY_POOL="http://127.0.0.1:7890,http://127.0.0.1:7891"
python server.py
```

## 健康检查

```text
GET /api/health
```

返回示例：

```json
{"ok": true, "service": "gzlib-shelf-finder"}
```

## 部署提示

如果部署平台支持 Procfile，可直接使用仓库中的：

```text
web: python server.py
```

如果平台要求启动命令，也可以直接填：

```bash
python server.py
```

## 说明

- 本工具仅作为信息整合与检索辅助，结果以广州图书馆官方系统为准。
- 请勿高频请求，不建议用于商业用途。
