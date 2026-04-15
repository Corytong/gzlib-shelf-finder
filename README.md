<<<<<<< HEAD
# Guangzhou Library Shelf Finder

一个面向广州图书馆联合目录 OPAC 的馆藏位置查询工具。

## 功能

- 多书名查询
- 作者单独查询或联合筛选
- 模糊查询开关
- 同一本书多位置展示
- 可借优先排序
- 本地 SQLite 缓存，减少重复请求
- 推荐图书快捷检索

## 技术栈

- 前端：原生 HTML / CSS / JavaScript
- 后端：Python 3 标准库 HTTP 服务
- 缓存：SQLite

## 启动

```bash
python server.py
```

然后访问 `http://127.0.0.1:8011`。

也可以使用 npm 脚本：

=======
# GZLib Shelf Finder

Guangzhou Library shelf address finder (local web UI). 通过广州图书馆联合目录 OPAC 进行馆藏位置查询，面向个人快速定位书架/书柜/楼层。

## Features
- 批量查询（一次查多本）
- 多馆藏位置合并展示
- 可借优先排序
- 本地 SQLite 缓存，减少重复请求
- 低依赖：HTML/CSS/JS + Python 标准库 HTTP server

## Dependencies / 环境要求
- Node.js 18/20（含 npm）
- Python 3.10+
- SQLite（随 Python 标准库）
- 当前 requirements.txt 无额外 pip 包（未来新增依赖可直接写入并 `pip install -r requirements.txt`）

## One-click install
```bash
./setup.sh
```
Windows：使用 Git Bash 执行
```bash
bash setup.sh
```

## Run
建议分两个终端运行：

后端服务：
```bash
source .venv/bin/activate
python server.py
```

前端：
>>>>>>> 17b75be1e64d885656db31d3655cf48cdeed0441
```bash
npm start
```

<<<<<<< HEAD
## 目录

- `index.html`：页面结构
- `styles.css`：界面样式
- `app.js`：前端交互逻辑
- `server.py`：代理、缓存和查询后端
- `data/`：运行后自动生成的本地缓存目录

## 说明

本工具仅作为信息索引助手，数据来源于广州图书馆公开查询系统，查询结果以官方为准。

本项目仅用于学习与个人使用。

数据来源于广州图书馆公开 OPAC 系统。

不对原系统进行任何破解或绕过，仅做信息整合与展示。

请勿高频请求或用于商业用途。
=======
访问：`http://127.0.0.1:8011`

## Project structure
```text
assets/
data/              # 运行时缓存（可清理）
index.html
styles.css
app.js
server.py
setup.sh
requirements.txt
```

## Screenshot（截图）
![UI](assets/ui.png)

## Safety & compliance（安全性与合规性）
- 仅供本地个人使用，不建议对外提供服务/商用。
- 请自行确认广州图书馆/联合目录 OPAC 服务条款（ToS）并遵循其使用限制。
- 内置基础限流（per-IP/per-process），避免过度请求对目标站造成压力；若你的网络环境特殊，请自行调整。
- 默认 SQLite 缓存仅用于加速；可随时删除 data/。
- 该工具不应用于抓取账户信息、登录态数据、敏感个人信息等行为。

## License
MIT
>>>>>>> 17b75be1e64d885656db31d3655cf48cdeed0441
