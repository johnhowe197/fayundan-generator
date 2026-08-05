"""
预提交验证脚本

在输出代码给用户之前运行此脚本，确保：
1. 代码语法正确
2. 模块导入正常
3. 核心功能不被破坏
4. 新功能实现正确
5. 符合需求要求

使用方法：
    python pre_commit_verify.py

或者在代码中调用：
    from pre_commit_verify import pre_commit_check
    if pre_commit_check():
        # 可以输出代码
        output_code()
    else:
        # 需要修复问题
        fix_issues()
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# 设置控制台编码为UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


class PreCommitVerifier:
    """预提交验证器"""

    def __init__(self):
        self.results = {
            'syntax': {'passed': [], 'failed': []},
            'imports': {'passed': [], 'failed': []},
            'core': {'passed': [], 'failed': []},
            'features': {'passed': [], 'failed': []},
            'regressions': {'passed': [], 'failed': []}
        }
        self.start_time = datetime.now()

    def verify_syntax(self):
        """验证代码语法"""
        print("\n[1/6] 验证代码语法...")

        python_files = list(project_root.rglob("*.py"))
        python_files = [f for f in python_files if "__pycache__" not in str(f)]

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                compile(code, str(py_file), 'exec')
                self.results['syntax']['passed'].append(py_file.name)
            except SyntaxError as e:
                self.results['syntax']['failed'].append(f"{py_file.name}: {e}")
            except Exception as e:
                self.results['syntax']['failed'].append(f"{py_file.name}: {e}")

    def verify_imports(self):
        """验证模块导入"""
        print("\n[2/6] 验证模块导入...")

        critical_modules = [
            ('models.bom_node', ['BOMNode', 'ExpandStatus', 'get_entity_name']),
            ('core.tree_builder', ['TreeBuilder']),
            ('core.calculator', ['ShippingCalculator']),
            ('core.exporter', ['ShippingExporter']),
            ('core.bom_parser', ['BOMParser']),
            ('utils.helpers', []),
        ]

        for module_name, classes in critical_modules:
            try:
                module = __import__(module_name, fromlist=[''])
                for class_name in classes:
                    if hasattr(module, class_name):
                        self.results['imports']['passed'].append(f"{module_name}.{class_name}")
                    else:
                        self.results['imports']['failed'].append(f"{module_name} 中找不到 {class_name}")
            except ImportError as e:
                self.results['imports']['failed'].append(f"{module_name}: {e}")
            except Exception as e:
                self.results['imports']['failed'].append(f"{module_name}: {e}")

    def verify_core_functions(self):
        """验证核心功能"""
        print("\n[3/6] 验证核心功能...")

        # 测试BOMNode
        try:
            from models.bom_node import BOMNode, ExpandStatus

            node = BOMNode(
                material_id="TEST001",
                parent_id="",
                name="测试物料",
                quantity=10,
                weight=1.5,
                level=0
            )

            assert node.material_id == "TEST001"
            assert node.quantity == 10
            assert node.expand_status == ExpandStatus.YES

            self.results['core']['passed'].append("BOMNode 创建和属性")
        except Exception as e:
            self.results['core']['failed'].append(f"BOMNode: {e}")

        # 测试TreeBuilder
        try:
            from core.tree_builder import TreeBuilder
            import pandas as pd

            builder = TreeBuilder()

            data = {
                '子物料号': ['M001', 'M002', 'M003'],
                '父物料号': ['', 'M001', 'M001'],
                '名称': ['根节点', '子节点1', '子节点2'],
                '数量': [1, 2, 3],
                '子物料净重': [1.0, 0.5, 0.3],
                'level': [0, 1, 1],
                '是否展开': ['是', '是', '是'],
                '图号': ['G001', 'G002', 'G003'],
                '规格': ['S001', 'S002', 'S003']
            }
            df = pd.DataFrame(data)

            root = builder.build_from_dataframe(df)

            assert root is not None
            assert len(builder.all_nodes) == 3
            assert len(root.children) == 2

            self.results['core']['passed'].append("TreeBuilder 构建树结构")
        except Exception as e:
            self.results['core']['failed'].append(f"TreeBuilder: {e}")

        # 测试BOMParser
        try:
            from core.bom_parser import BOMParser

            parser = BOMParser()

            assert parser.parse_layer('0') == 0
            assert parser.parse_layer('1') == 1
            assert parser.parse_layer('.2') == 2
            assert parser.parse_layer('..3') == 3

            self.results['core']['passed'].append("BOMParser 层号解析")
        except Exception as e:
            self.results['core']['failed'].append(f"BOMParser: {e}")

    def verify_features(self):
        """验证功能实现"""
        print("\n[4/6] 验证功能实现...")

        # 验证BOM拆分功能
        try:
            from core.bom_parser import BOMParser
            import pandas as pd

            parser = BOMParser()

            # 测试数据
            data = {
                '层号': ['0', '1'],
                '子物料号': ['P001', 'C001'],
                '父物料号': ['', 'P001'],
                '名称': ['产品', '零件  GB/T 5782 M12'],
                '数量': [1, 2],
                '子物料净重': [10, 0.5],
                '子物料图号': ['', ''],
                '型号': ['', ''],
                '物料加工路线': ['M-J', 'W-D']
            }
            df = pd.DataFrame(data)

            cleaned = parser._clean_data(df.copy())

            # 检查物料加工路线被删除
            if '物料加工路线' not in cleaned.columns:
                self.results['features']['passed'].append("物料加工路线列已删除")
            else:
                self.results['features']['failed'].append("物料加工路线列未删除")

            # 检查图号规格拆分
            row = cleaned[cleaned['子物料号'] == 'C001'].iloc[0]
            if row['图号'] == 'GB/T 5782' and row['规格'] == 'M12':
                self.results['features']['passed'].append("图号规格拆分正确")
            else:
                self.results['features']['failed'].append("图号规格拆分错误")

        except Exception as e:
            self.results['features']['failed'].append(f"BOM拆分功能: {e}")

        # 验证隐藏功能
        try:
            from core.tree_builder import TreeBuilder
            from models.bom_node import ExpandStatus
            import pandas as pd

            builder = TreeBuilder()

            data = {
                '子物料号': ['ROOT', 'CHILD1', 'CHILD2'],
                '父物料号': ['', 'ROOT', 'ROOT'],
                '名称': ['根', '子1', '子2'],
                '数量': [1, 2, 3],
                '子物料净重': [10, 1, 2],
                'level': [0, 1, 1],
                '是否展开': ['是', '是', '否'],
                '图号': ['', '', ''],
                '规格': ['', '', '']
            }
            df = pd.DataFrame(data)

            root = builder.build_from_dataframe(df)

            # 检查是否展开=否
            child2 = [c for c in root.children if c.material_id == 'CHILD2'][0]
            if child2.expand_status == ExpandStatus.NO:
                self.results['features']['passed'].append("是否展开=否 设置正确")
            else:
                self.results['features']['failed'].append("是否展开=否 设置错误")

        except Exception as e:
            self.results['features']['failed'].append(f"隐藏功能: {e}")

    def verify_regressions(self):
        """验证没有回归问题"""
        print("\n[5/6] 验证回归问题...")

        try:
            from ui.main_window import MainWindow

            critical_methods = [
                'import_bom_data',
                'refresh_tree',
                '_add_tree_item',
                '_show_selection_menu',
                '_set_item_value',
                'on_item_changed',
                '_hide_children',
                '_show_children',
                '_is_node_hidden',
                'validate_config',
                'show_preview',
                'save_progress',
                'load_progress',
            ]

            for method in critical_methods:
                if hasattr(MainWindow, method) and callable(getattr(MainWindow, method)):
                    self.results['regressions']['passed'].append(f"方法 {method}")
                else:
                    self.results['regressions']['failed'].append(f"方法 {method} 缺失")

        except Exception as e:
            self.results['regressions']['failed'].append(f"UI检查: {e}")

    def print_results(self):
        """输出验证结果"""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        print("\n" + "=" * 70)
        print("预提交验证结果")
        print("=" * 70)

        total_passed = 0
        total_failed = 0

        for category, results in self.results.items():
            passed = len(results['passed'])
            failed = len(results['failed'])
            total_passed += passed
            total_failed += failed

            if passed > 0:
                print(f"\n[PASS] {category.upper()} ({passed} passed):")
                for item in results['passed']:
                    print(f"   + {item}")

            if failed > 0:
                print(f"\n[FAIL] {category.upper()} ({failed} failed):")
                for item in results['failed']:
                    print(f"   - {item}")

        print("\n" + "=" * 70)
        print(f"Total: {total_passed} passed, {total_failed} failed")
        print(f"Duration: {duration:.2f} seconds")

        if total_failed == 0:
            print("\n[PASS] Verification passed - safe to output code")
        else:
            print("\n[FAIL] Verification failed - fix issues before output")

        print("=" * 70)

        return total_failed == 0


def pre_commit_check():
    """
    预提交检查函数

    在输出代码给用户之前调用此函数

    返回值:
        True: 验证通过，可以输出代码
        False: 验证失败，需要修复问题
    """
    verifier = PreCommitVerifier()

    verifier.verify_syntax()
    verifier.verify_imports()
    verifier.verify_core_functions()
    verifier.verify_features()
    verifier.verify_regressions()

    return verifier.print_results()


if __name__ == "__main__":
    success = pre_commit_check()
    sys.exit(0 if success else 1)
