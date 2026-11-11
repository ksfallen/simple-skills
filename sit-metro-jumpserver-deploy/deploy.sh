#!/bin/bash
# 跳板机服务部署工具启动脚本
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python "$SCRIPT_DIR/deploy_jumpserver.py" "$@"
