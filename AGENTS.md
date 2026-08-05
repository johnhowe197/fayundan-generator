# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

发运单生成器是一款离线桌面应用，用于处理ERP系统中多级BOM数据的发运单生成。主要解决同一物料号在不同发运方式/主体下的数量拆分、打捆件内部子件边界处理、递归计算最终数量等问题。

## 技术栈

- Python 3.9+
- PyQt5 5.15+ (GUI框架)
- Pandas 1.3+ (数据处理)
- OpenPyXL 3.0+ (Excel处理)
- PyInstaller 5.0+ (打包)

## 常用命令

```bash
# 运行程序
python main.py

# 安装依赖
pip install -r requirements.txt

# 打包成EXE
pyinstaller --name="发运单生成器" --windowed --onefile main.py

# 运行预提交验证
python pre_commit_verify.py
```

## 核心架构

### 四层架构
```
表现层 (UI Layer)     → ui/模块
业务逻辑层 (Business) → core/模块  
数据层 (Data Layer)   → models/模块
工具层 (Utility)     → utils/模块
```

### 核心模块职责
- **models/bom_node.py**: BOM节点数据模型，包含树结构关系、发运配置、计算结果
- **core/tree_builder.py**: 将平面BOM数据转换为树结构
- **core/calculator.py**: 递归计算最终数量和三重聚合
- **core/bom_parser.py**: 清洗和映射ERP原始数据
- **core/exporter.py**: 导出格式化的Excel发运单
- **ui/main_window.py**: 主窗口，包含工具栏、树视图、预览表格、状态栏

### 关键算法
1. **最终数量计算**: 子节点数量 = 自身用量 × 父节点最终数量
2. **三重聚合**: 按物料号+发运主体+发运方式+备注分组求和
3. **分组排序**: 01-20→1, 98→2, 90-91→3, 99→4, 00→5

### 数据流
```
Excel/CSV → BOMParser → TreeBuilder → ShippingCalculator → ShippingExporter
```

## 代码约定

- 所有UI文本、注释、日志使用中文
- 类名使用PascalCase，方法名使用snake_case
- 数据模型使用`@dataclass`装饰器
- 异常处理采用try-except模式，记录到error.log
- 配置文件存储在`config/entity_definition.json`

## 重要文件

- `pre_commit_verify.py`: 预提交验证脚本，检查语法、导入、核心功能
- `config/entity_definition.json`: 发运主体代码映射
- `docs/开发计划.md`: 完整开发计划和技术架构
- `docs/待办事项.md`: 当前待办事项

## 开发注意事项

1. 修改UI时注意PyQt5的信号槽机制
2. 计算引擎修改需验证递归逻辑正确性
3. 导出功能修改需测试中文编码(UTF-8-BOM)
4. 使用`pre_commit_verify.py`验证修改

## 开发编排器

**目标:** 通过 Architect→Developer→QA 三代理流水线，确保每次变更经过设计、实现、验证三阶段。

**触发条件：**
- 跨多个模块的复杂功能开发（新增模块、重构架构、修改数据流）
- 修改涉及数据模型、计算引擎、导出格式的核心逻辑
- 打包部署配置变更（PyInstaller、依赖管理）

**不需要触发（直接处理）：**
- 单文件的简单修改（修 bug、改 UI 文案、加按钮、改提示逻辑）
- 纯询问性问题
- 调试和测试脚本编写

**变更历史：**
| 日期 | 变更内容 | 目标 | 理由 |
|------|----------|------|------|
| 2026-06-17 | 初始配置 | 全部 | 建立开发编排器，引入三代理流水线 |
