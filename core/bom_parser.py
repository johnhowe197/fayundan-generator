"""
BOM数据解析器

解析ERP导出的多级BOM数据，清洗并转换为标准格式
"""

import pandas as pd
import re
from pathlib import Path
from typing import Optional, Tuple


class BOMParser:
    """BOM数据解析器"""

    # 需要删除的无效字段
    INVALID_FIELDS = [
        '层号', '领料标志', '发货', '单位', '报废系数%',
        '来源', '审核', '父物料plmid', '子物料plmid',
        '物料加工路线', '品牌'
    ]

    # 字段映射关系
    COLUMN_MAPPING = {
        '子物料号': '子物料号',
        '父物料号': '父物料号',
        '名称': '名称',
        '数量': '数量',
        '子物料净重': '子物料净重',
        '子物料图号': '图号',
        '备注': '备注'
    }

    def __init__(self):
        self.project_id: str = ""
        self.original_data: Optional[pd.DataFrame] = None
        self.cleaned_data: Optional[pd.DataFrame] = None

    def _split_name_field(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        拆分名称字段中的多个部分（当图号和规格列为空时）
        
        按照以下规则进行拆分：
        1. 先按多个连续空格（≥2个）进行第一级拆分
        2. 第1部分：名称
        3. 第2部分：需要进一步拆分成图号和规格的起始部分
           - 如果第2部分以标准号前缀（GB、ISO等）开头，图号包括该前缀及后一个词
           - 否则第一个词是图号
        4. 规格：第2部分的剩余词 + 第3部分及以后
        
        例如："防松螺母 细牙  GB/T 889.2 M30*2        10" 会被拆分为：
        - 名称: "防松螺母 细牙"
        - 图号: "GB/T 889.2" （GB标准 + 数字）
        - 规格: "M30*2 10"
        
        Args:
            df: 包含名称、图号、规格字段的DataFrame
            
        Returns:
            拆分后的DataFrame
        """
        if '名称' not in df.columns:
            return df

        # 空表守卫：0 行 DataFrame 上 apply 不会执行函数、无法推断列，
        # 直接返回避免后续 split_results['name'] 抛 KeyError
        if df.empty:
            return df

        # 确保相关列存在（注意：字段在重命名后是'图号'和'规格'）
        if '图号' not in df.columns:
            df['图号'] = ''
        if '规格' not in df.columns:
            df['规格'] = ''
        
        # 标准号前缀列表
        standard_prefixes = ['GB', 'ISO', 'ANSI', 'DIN', 'JIS', 'EN', 'GOST']

        # 材质模式（匹配以下格式）：
        # - 30CRMNTI, 27SiMn, 23MnCrNiMo54 等（2-3位数字 + 2位以上字母 + 可选数字，排除标准号前缀）
        # - Q235, Q355 等（Q + 3位数字）
        # - ZG230-450, ZG30SiMnMo 等（ZG + 数字 + 可选字母/连字符+数字）
        # - 304, 316L 等（2-3位数字 + 可选1位字母，但排除M12/M16等螺栓规格）
        material_pattern = re.compile(
            r'^(?!M\d|GB|ISO|ANSI|DIN|JIS|EN|GOST)'  # 排除螺栓和标准号
            r'('
            r'ZG\d{2,}[A-Za-z]*(-\d+)*'  # ZG230-450, ZG30SiMnMo
            r'|\d{2,3}[A-Za-z]{2,}\d*'    # 30CRMNTI, 27SiMn, 23MnCrNiMo54
            r'|\d{2,3}[A-Za-z]+\(.*\)'    # 27SiMn(禁用)
            r'|Q\d{3}[A-Za-z]?'            # Q235, Q355, Q355B
            r'|\d{2,3}[A-Za-z]?$'         # 304, 316L (简单数字+可选字母)
            r')$',
            re.IGNORECASE
        )

        # 工艺路线模式（如M-J-M, W-D, Z-X等，包含X-R-J-B这种格式）
        process_pattern = re.compile(r'^[A-Z](-[A-Z])+$', re.IGNORECASE)  # 如M-J-M, W-D, X-R-J-B

        # 单字母工艺路线（如"A"、"Z"等）
        single_letter_process = re.compile(r'^[A-Z]$', re.IGNORECASE)

        # 厚度信息（如δ40、δ12、δ=40等，δ=delta表示板材厚度）
        thickness_pattern = re.compile(r'^δ\d+\.?\d*$', re.IGNORECASE)

        # 工艺标记前缀（如"组件A"、"零件B"等，只过滤特定工艺前缀，不影响"插板J"等真实零件名）
        process_prefixes = ['组件', '零件', '毛坯', '半成品', '成品', '在制品']

        # 创建新列用于存储拆分结果
        def split_parts(row):
            name_str = row['名称']

            if not name_str or pd.isna(name_str):
                return pd.Series({'name': '', 'drawing': '', 'spec': ''})

            # 将字符串转换为str类型并去除两端空格
            name_str = str(name_str).strip()

            # 检查是否是纯材质、工艺路线或厚度信息（如"Q355"、"M-J-M"、"δ40"）
            parts = name_str.split()
            if len(parts) <= 2:
                # 检查是否全是材质、工艺路线或厚度信息
                is_material_or_process = all(
                    material_pattern.match(p) or process_pattern.match(p) or thickness_pattern.match(p)
                    for p in parts
                )
                if is_material_or_process:
                    return pd.Series({'name': '', 'drawing': '', 'spec': ''})

            # 检查是否是工艺标记格式（如"组件A"），且没有标准号前缀
            # 只过滤特定工艺前缀（组件、零件等），不影响"插板J"等真实零件名
            if len(parts) <= 2:
                has_std_prefix = any(
                    any(word.startswith(prefix) for prefix in standard_prefixes)
                    for word in parts
                )
                if not has_std_prefix:
                    # 检查是否包含工艺路线格式
                    has_process = any(process_pattern.match(p) for p in parts)
                    # 检查是否是工艺标记前缀+字母格式（如"组件A"）
                    has_process_prefix = any(
                        any(p.startswith(prefix) and len(p) <= len(prefix) + 2 for prefix in process_prefixes)
                        for p in parts
                    )
                    if has_process or has_process_prefix:
                        return pd.Series({'name': '', 'drawing': '', 'spec': ''})

            # 首先尝试按多个连续空格分割（至少2个空格）
            major_parts = re.split(r'  +', name_str)

            if len(major_parts) >= 2:
                # 有多空格分隔的情况
                name = major_parts[0].strip()
                second_part = major_parts[1].strip()
                second_words = second_part.split()

                # 查找标准号前缀的位置
                std_prefix_idx = -1
                for i, word in enumerate(second_words):
                    if any(word.startswith(prefix) for prefix in standard_prefixes):
                        std_prefix_idx = i
                        break

                # 标准号之前：过滤材质、工艺路线和单字母工艺标记；标准号之后：保留所有作为规格
                if std_prefix_idx >= 0:
                    # 标准号之前的部分：过滤材质、工艺路线和单字母工艺标记
                    before_std = []
                    for word in second_words[:std_prefix_idx]:
                        if (not material_pattern.match(word) and
                            not process_pattern.match(word) and
                            not single_letter_process.match(word) and
                            not thickness_pattern.match(word)):
                            before_std.append(word)

                    # 标准号及之后的部分：保留所有
                    after_std = second_words[std_prefix_idx:]

                    filtered_words = before_std + after_std
                else:
                    # 没有标准号，过滤材质、工艺路线、单字母工艺标记和厚度信息
                    filtered_words = []
                    for word in second_words:
                        if (not material_pattern.match(word) and
                            not process_pattern.match(word) and
                            not single_letter_process.match(word) and
                            not thickness_pattern.match(word)):
                            filtered_words.append(word)

                # 确定图号和规格
                drawing = ''
                spec_parts = []

                if len(filtered_words) >= 1:
                    first_word = filtered_words[0]
                    has_std_prefix = any(first_word.startswith(prefix) for prefix in standard_prefixes)

                    if has_std_prefix:
                        # 有标准号前缀：需要正确分割标准号和规格
                        # 情况1: 标准号是完整的一个词 → "GB/T96.1-2002 φ24"
                        # 情况2: 标准号被空格拆成两个词 → "GB/T 5782 M12"
                        std_end_idx = 0
                        if len(filtered_words) > 1:
                            next_word = filtered_words[1]
                            # 下一个是纯数字、小数、或数字-年份格式 → 标准号的一部分
                            # 如 "5782" in "GB/T 5782"
                            # 如 "889.2" in "GB/T 889.2"
                            # 如 "856-1988" in "GB/T 856-1988"
                            if (next_word.isdigit() or
                                re.match(r'^\d+\.\d+$', next_word) or
                                re.match(r'^\d{3,4}(-\d{2,4})?$', next_word)):
                                std_end_idx = 1
                        drawing = ' '.join(filtered_words[:std_end_idx + 1])
                        spec_parts = filtered_words[std_end_idx + 1:]
                    else:
                        # 没有标准号前缀，第一个词是图号，剩余是规格
                        # 如：LS098 SGZ1200/2400 → 图号=LS098, 规格=SGZ1200/2400
                        drawing = first_word
                        spec_parts = filtered_words[1:]

                drawing = drawing

                # 第三部分及以后的内容也加入规格
                if len(major_parts) > 2:
                    # 第三部分及以后：过滤材质、工艺路线、单字母工艺标记和厚度信息
                    for part in major_parts[2:]:
                        for word in part.split():
                            if (not material_pattern.match(word) and
                                not process_pattern.match(word) and
                                not single_letter_process.match(word) and
                                not thickness_pattern.match(word)):
                                spec_parts.append(word)

                spec = ' '.join(spec_parts)
                return pd.Series({'name': name, 'drawing': drawing, 'spec': spec})

            # 没有多空格分隔，尝试按标准号前缀拆分（如 "防松螺母 GB/T 5782 M16*45"）
            all_words = name_str.split()
            if len(all_words) >= 2:
                # 查找标准号前缀出现的位置
                for i, word in enumerate(all_words):
                    has_std_prefix = any(word.startswith(prefix) for prefix in standard_prefixes)
                    if has_std_prefix:
                        # 找到标准号前缀，前面的是名称，后面的是图号和规格
                        name = ' '.join(all_words[:i]).strip()

                        # 图号：从标准号开始，通常是"GB/T 数字"两个词
                        drawing_word_count = 2 if i + 1 < len(all_words) else 1
                        drawing = ' '.join(all_words[i:i + drawing_word_count])

                        # 规格：剩余部分
                        spec = ' '.join(all_words[i + drawing_word_count:])

                        if name:  # 只有名称非空时才返回拆分结果
                            return pd.Series({'name': name, 'drawing': drawing, 'spec': spec})
                        break

            # 无法拆分，全部作为名称
            return pd.Series({'name': name_str, 'drawing': '', 'spec': ''})
        
        # 应用拆分函数
        split_results = df[['名称', '图号', '规格']].apply(split_parts, axis=1)
        
        # 将拆分结果更新到原始列
        # 对名称列：总是使用拆分后的名称（去掉前面的多字段信息）
        df['名称'] = split_results['name']
        
        # 对图号列：只在原值为空时才使用拆分结果
        df['图号'] = df['图号'].fillna('')
        empty_drawing_mask = (df['图号'] == '') | (df['图号'].isna())
        df.loc[empty_drawing_mask, '图号'] = split_results.loc[empty_drawing_mask, 'drawing']

        # 对规格列：只在原值为空时才使用拆分结果（与图号列处理一致，避免覆盖ERP自带的规格）
        df['规格'] = df['规格'].fillna('')
        empty_spec_mask = (df['规格'] == '') | (df['规格'].isna())
        df.loc[empty_spec_mask, '规格'] = split_results.loc[empty_spec_mask, 'spec'].fillna('')

        return df

    def _clean_spec_field(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗规格列，过滤掉材质工艺路线数据（如"组件 A"、"DN10 组件"）

        Args:
            df: DataFrame

        Returns:
            清洗后的DataFrame
        """
        if '规格' not in df.columns:
            return df

        def clean_spec(spec_str):
            if not spec_str or pd.isna(spec_str):
                return ''

            spec_str = str(spec_str).strip()
            if not spec_str:
                return ''

            # 如果规格包含"组件"，直接过滤掉
            if '组件' in spec_str:
                return ''

            return spec_str

        df['规格'] = df['规格'].apply(clean_spec)
        return df

    def parse_layer(self, layer_str) -> int:
        """
        将层号字符串转换为数字

        原始格式：
        - 0: 顶级节点
        - 1: 第一层
        - .2: 第二层
        - ..3: 第三层
        - ...4: 第四层
        - ....5: 第五层
        - .....6: 第六层
        - ......7: 第七层

        Args:
            layer_str: 层号字符串

        Returns:
            层数字
        """
        if pd.isna(layer_str):
            return 0

        layer_str = str(layer_str).strip()

        if layer_str == '0':
            return 0
        elif layer_str == '1':
            return 1
        else:
            # 计算点号数量
            dots = layer_str.count('.')
            return dots + 1

    def _read_csv_any_encoding(self, file_path: Path) -> pd.DataFrame:
        """
        依次尝试常见编码读取CSV

        很多ERP系统的CSV导出为 GBK/GB18030 编码，直接按 UTF-8 读取会抛
        UnicodeDecodeError。此处按 UTF-8 → GBK → GB18030 顺序回退解码。

        Args:
            file_path: CSV文件路径

        Returns:
            读取的DataFrame
        """
        last_err = None
        for enc in ('utf-8-sig', 'gbk', 'gb18030'):
            try:
                return pd.read_csv(file_path, encoding=enc)
            except UnicodeDecodeError as e:
                last_err = e
                continue
        raise ValueError(
            f"无法识别CSV文件编码（已尝试 UTF-8/GBK/GB18030）：{file_path.name}"
        ) from last_err

    def parse(self, file_path: str, project_id: Optional[str] = None) -> pd.DataFrame:
        """
        解析BOM文件

        Args:
            file_path: 文件路径
            project_id: 项目编号（可选，如果为None则从文件名提取）

        Returns:
            清洗后的DataFrame
        """
        file_path = Path(file_path)

        # 提取项目编号
        if project_id is None:
            project_id = self._extract_project_id(file_path.name)
        self.project_id = project_id

        # 读取文件
        if file_path.suffix.lower() == '.csv':
            df = self._read_csv_any_encoding(file_path)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")

        self.original_data = df

        # 清洗数据
        self.cleaned_data = self._clean_data(df)

        return self.cleaned_data

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        清洗数据

        Args:
            df: 原始DataFrame

        Returns:
            清洗后的DataFrame
        """
        # 0. 入口校验：空表与必需列（给出清晰中文错误，避免裸 KeyError 堆栈）
        if df.empty:
            raise ValueError("BOM文件没有数据行（只有表头或为空），请检查文件。")
        required_cols = ['子物料号', '父物料号', '数量', '子物料净重']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"BOM文件缺少必需列：{'、'.join(missing)}。请检查ERP导出格式。")

        # 1. 清洗层号字段
        if '层号' in df.columns:
            df['level'] = df['层号'].apply(self.parse_layer)
        else:
            # 如果没有层号字段，尝试使用level字段
            df['level'] = pd.to_numeric(df.get('level', 0), errors='coerce').fillna(0).astype(int)

        # 2. 删除无效字段（支持列名有空格的情况）
        fields_to_remove = []
        for f in self.INVALID_FIELDS:
            # 精确匹配
            if f in df.columns:
                fields_to_remove.append(f)
            else:
                # 尝试去除空格后匹配
                for col in df.columns:
                    if str(col).strip() == f:
                        fields_to_remove.append(col)
                        break
        df_cleaned = df.drop(columns=fields_to_remove, errors='ignore')

        # 3. 重命名字段
        rename_map = {k: v for k, v in self.COLUMN_MAPPING.items() if k in df_cleaned.columns}
        df_cleaned = df_cleaned.rename(columns=rename_map)

        # 4. 添加项目编号
        if '项目编号' in df_cleaned.columns:
            df_cleaned['项目编号'] = self.project_id
        else:
            df_cleaned.insert(0, '项目编号', self.project_id)

        # 5. 添加是否展开字段（默认全部为"否"，用户逐层维护）
        df_cleaned['是否展开'] = '否'

        # 6. 数据类型转换
        df_cleaned['数量'] = pd.to_numeric(df_cleaned['数量'], errors='coerce').fillna(0)
        df_cleaned['子物料净重'] = pd.to_numeric(df_cleaned['子物料净重'], errors='coerce').fillna(0)
        df_cleaned['level'] = pd.to_numeric(df_cleaned['level'], errors='coerce').fillna(0).astype(int)

        # 7. 修正顶级节点的数量为1
        top_nodes = df_cleaned['level'] == 0
        df_cleaned.loc[top_nodes, '数量'] = 1

        # 8. 拆分名称字段中的多个部分（名称、图号、规格）
        df_cleaned = self._split_name_field(df_cleaned)

        # 9. 过滤规格列中的材质工艺路线数据（如"组件 A"）
        if '规格' in df_cleaned.columns:
            df_cleaned = self._clean_spec_field(df_cleaned)

        # 10. 填充空值
        for col in ['图号', '规格', '名称', '备注']:
            if col in df_cleaned.columns:
                df_cleaned[col] = df_cleaned[col].fillna('')

        df_cleaned['父物料号'] = df_cleaned['父物料号'].fillna('')
        df_cleaned['父物料号'] = df_cleaned['父物料号'].replace('nan', '')

        # 11. 删除子物料号为空的行
        df_cleaned = df_cleaned[df_cleaned['子物料号'].notna()]

        # 12. 重新排列列顺序
        column_order = ['项目编号', '子物料号', '父物料号', '图号', '规格', '名称', '数量', '子物料净重', '是否展开', 'level', '序号']
        for col in column_order:
            if col not in df_cleaned.columns:
                df_cleaned[col] = ''

        df_cleaned = df_cleaned[column_order]

        return df_cleaned

    def _extract_project_id(self, filename: str) -> str:
        """
        从文件名中提取项目编号

        Args:
            filename: 文件名

        Returns:
            项目编号
        """
        # 尝试匹配常见的项目编号格式
        patterns = [
            r'(LS\d+)',
            r'(ls\d+)',
            r'([A-Z]{2}\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return match.group(1).upper()

        # 如果没有匹配到，返回默认值
        return "UNKNOWN"

    def get_statistics(self) -> dict:
        """
        获取数据统计信息

        Returns:
            统计信息字典
        """
        if self.cleaned_data is None:
            return {}

        df = self.cleaned_data

        return {
            'total_rows': len(df),
            'unique_materials': df['子物料号'].nunique(),
            'top_level_nodes': len(df[df['level'] == 0]),
            'leaf_nodes': len(df[df['是否展开'] == '否']),
            'level_distribution': df['level'].value_counts().sort_index().to_dict()
        }

    def save(self, output_file: str):
        """
        保存清洗后的数据

        Args:
            output_file: 输出文件路径
        """
        if self.cleaned_data is None:
            raise ValueError("没有可保存的数据，请先执行parse()")

        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if output_path.suffix.lower() == '.csv':
            self.cleaned_data.to_csv(output_path, index=False, encoding='utf-8-sig')
        elif output_path.suffix.lower() in ['.xlsx', '.xls']:
            self.cleaned_data.to_excel(output_path, index=False, engine='openpyxl')
        else:
            raise ValueError(f"不支持的文件格式: {output_path.suffix}")
