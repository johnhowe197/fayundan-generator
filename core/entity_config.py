"""
发运主体配置管理模块

管理发运主体定义和预设配置的读写
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class EntityConfigManager:
    """发运主体配置管理器（唯一数据源）"""

    # 默认发运主体定义：(代码, 名称, 说明)
    DEFAULT_ENTITIES = [
        ('01', '机头', '物理分组'),
        ('02', '左过渡槽', '物理分组'),
        ('03', '左偏转槽5', '物理分组'),
        ('04', '左偏转槽4', '物理分组'),
        ('05', '左偏转槽3', '物理分组'),
        ('06', '左偏转槽2', '物理分组'),
        ('07', '左偏转槽1', '物理分组'),
        ('08', '电缆槽', '物理分组'),
        ('09', '特殊电缆槽', '物理分组'),
        ('10', '中部槽', '物理分组'),
        ('11', '开天窗中部槽', '物理分组'),
        ('12', '右偏转槽1', '物理分组'),
        ('13', '右偏转槽2', '物理分组'),
        ('14', '右偏转槽3', '物理分组'),
        ('15', '右偏转槽4', '物理分组'),
        ('16', '右偏转槽5', '物理分组'),
        ('17', '右过渡槽', '物理分组'),
        ('20', '机尾', '物理分组'),
        ('21', '推移梁', '物理分组'),
        ('22', '推移座', '物理分组'),
        ('90', '自定义改动', '特殊'),
        ('91', '自定义2', '特殊'),
        ('92', '自定义3', '特殊'),
        ('93', '自定义4', '特殊'),
        ('94', '自定义5', '特殊'),
        ('95', '液压管路', '特殊'),
        ('96', '换面件', '特殊'),
        ('97', '增供件', '特殊'),
        ('98', '捆装发运类', '特殊'),
        ('99', '整合装箱类', '特殊'),
        ('00', '无序号特殊发运', '特殊'),
    ]

    # 不可删除的锁定代码
    LOCKED_CODES = {'95', '96', '97', '98', '99', '00'}

    # 发运主体 → 发运方式 自动规则
    AUTO_METHOD_RULES = {
        '98': 'B',  # 捆装发运类 → 打捆
        '99': 'C',  # 整合装箱类 → 装箱
    }

    # 物理分组代码（01-89，包含用户自定义区间）
    PHYSICAL_GROUP_CODES = {str(i).zfill(2) for i in range(1, 90)}

    # 分组排序规则：代码 → 排序优先级
    GROUP_SORT_MAP = {
        **{str(i).zfill(2): 1 for i in range(1, 90)},  # 01-89 → 1（物理分组+用户自定义）
        '98': 2,  # 捆装发运类
        **{str(i).zfill(2): 3 for i in range(90, 98)},  # 90-97 → 3
        '99': 4,  # 整合装箱类
        '00': 5,  # 无序号特殊发运
    }

    # 发运方式排序规则
    METHOD_SORT_MAP = {'B': 1, 'A': 2, 'C': 3, 'D': 4}

    # ========== 类级缓存（避免重复读取配置文件） ==========
    _cached_entity_map: Optional[Dict[str, str]] = None

    def __init__(self, config_dir: Optional[Path] = None):
        """
        初始化配置管理器

        Args:
            config_dir: 配置文件目录，默认为可写应用目录下的 config/
                        （打包后为 EXE 所在目录/config，开发环境为项目 config/）
        """
        if config_dir is None:
            from utils.helpers import get_writable_app_dir
            config_dir = get_writable_app_dir() / 'config'
        self.config_dir = Path(config_dir)
        # 最近一次保存失败的原因（供 UI 向用户展示真实错误，杜绝"假保存成功"）
        self.last_error = ''
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # 目录不可创建不致命：读取会回退到内置默认值；
            # 保存时通过 last_error 向用户暴露真实原因
            self.last_error = f'配置目录无法创建: {self.config_dir}（{e}）'
            logging.error(self.last_error)

        self._entity_file = self.config_dir / 'entity_definition.json'
        self._preset_file = self.config_dir / 'shipping_presets.json'

        # 打包环境下首次运行把出厂默认配置从只读资源目录播种到可写目录，
        # 保证用户读到出厂配置内容，且后续修改能持久化（修复 onefile 配置静默丢失）
        from utils.helpers import get_bundle_dir, seed_file_from_bundle
        bundle_config = get_bundle_dir() / 'config'
        seed_file_from_bundle(bundle_config / 'entity_definition.json', self._entity_file)
        seed_file_from_bundle(bundle_config / 'shipping_presets.json', self._preset_file)

    # ========== 静态方法：统一数据访问接口 ==========

    @staticmethod
    def get_entity_name(entity_code: str) -> str:
        """
        获取发运主体名称（只返回名称，不包含代码前缀）

        Args:
            entity_code: 发运主体代码（如 '01' 或 '01-机头'）

        Returns:
            发运主体名称（如 '机头'）
        """
        if not entity_code:
            return ''
        # 如果已经包含前缀，只返回名称部分
        if '-' in entity_code:
            return entity_code.split('-', 1)[1]
        # 从配置获取
        entity_map = EntityConfigManager.get_static_entity_map()
        return entity_map.get(entity_code, entity_code)

    @staticmethod
    def get_entity_display_name(entity_code: str) -> str:
        """
        获取发运主体显示名称（包含代码前缀）

        Args:
            entity_code: 发运主体代码（如 '01'）

        Returns:
            发运主体显示名称（如 '01-机头'）
        """
        if not entity_code:
            return ''
        # 如果已经包含完整前缀，直接返回
        if '-' in entity_code:
            return entity_code
        # 从配置获取
        entity_map = EntityConfigManager.get_static_entity_map()
        name = entity_map.get(entity_code, '')
        if name:
            return f'{entity_code}-{name}'
        return entity_code

    @staticmethod
    def get_static_entity_map() -> Dict[str, str]:
        """
        获取发运主体映射（静态方法，带缓存）

        Returns:
            {code: name} 格式的映射字典（值为不带代码前缀的纯名称）

        注意：缓存格式统一为 {code: name}（不带前缀），与
        update_entity_name_map / save_definitions 的写入格式保持一致。
        get_entity_name / get_entity_display_name 均按此契约消费。
        """
        if EntityConfigManager._cached_entity_map is None:
            mgr = EntityConfigManager()
            EntityConfigManager._cached_entity_map = {
                code: name for code, name, desc in mgr.load_definitions()
            }
        return EntityConfigManager._cached_entity_map

    @staticmethod
    def update_entity_name_map(entities: list):
        """
        更新发运主体名称映射（兼容旧接口）

        Args:
            entities: 发运主体列表，格式为 [(code, name, desc), ...]
        """
        EntityConfigManager._cached_entity_map = {code: name for code, name, desc in entities}

    @staticmethod
    def apply_auto_rules(node) -> None:
        """
        应用自动规则（如 98→B打捆, 99→C装箱）

        Args:
            node: BOMNode 节点
        """
        if node.shipping_entity in EntityConfigManager.AUTO_METHOD_RULES:
            node.shipping_method = EntityConfigManager.AUTO_METHOD_RULES[node.shipping_entity]

    @staticmethod
    def get_group_sort(entity_code: str) -> int:
        """
        获取分组排序值

        Args:
            entity_code: 发运主体代码

        Returns:
            排序值（1-6）
        """
        if not entity_code:
            return 6
        code = entity_code.split('-')[0] if '-' in entity_code else entity_code
        return EntityConfigManager.GROUP_SORT_MAP.get(code, 6)

    @staticmethod
    def get_method_sort(method_code: str) -> int:
        """
        获取发运方式排序值

        Args:
            method_code: 发运方式代码

        Returns:
            排序值（1-5）
        """
        if not method_code:
            return 5
        return EntityConfigManager.METHOD_SORT_MAP.get(method_code, 5)

    @staticmethod
    def _get_locked_entities() -> Dict[str, str]:
        """
        获取锁定代码的默认定义

        Returns:
            {code: name} 格式的锁定代码映射
        """
        return {
            code: name
            for code, name, desc in EntityConfigManager.DEFAULT_ENTITIES
            if code in EntityConfigManager.LOCKED_CODES
        }

    @staticmethod
    def _ensure_locked_codes(entities: Dict[str, str]) -> Dict[str, str]:
        """
        确保锁定代码存在于实体映射中

        Args:
            entities: 原始实体映射

        Returns:
            包含锁定代码的实体映射
        """
        result = dict(entities)
        for code, name in EntityConfigManager._get_locked_entities().items():
            if code not in result:
                result[code] = name
        return result

    # ========== 发运主体定义 ==========

    def load_definitions(self) -> List[Tuple[str, str, str]]:
        """
        加载发运主体定义（自动确保锁定代码存在）

        Returns:
            发运主体列表，格式为 [(code, name, desc), ...]
        """
        entities = None
        try:
            if self._entity_file.exists():
                with open(self._entity_file, 'r', encoding='utf-8') as f:
                    entities = json.load(f)
        except Exception as e:
            logging.error(f"加载发运主体定义失败: {e}")

        if entities is None:
            entities = self.DEFAULT_ENTITIES.copy()

        # 确保锁定代码存在
        existing_codes = {code for code, name, desc in entities}
        locked_defaults = {
            code: (code, name, desc)
            for code, name, desc in self.DEFAULT_ENTITIES
            if code in self.LOCKED_CODES
        }
        for code, item in locked_defaults.items():
            if code not in existing_codes:
                entities.append(item)

        return entities

    def save_definitions(self, entities: List[Tuple[str, str, str]]) -> bool:
        """
        保存发运主体定义

        Args:
            entities: 发运主体列表，格式为 [(code, name, desc), ...]

        Returns:
            是否保存成功
        """
        try:
            with open(self._entity_file, 'w', encoding='utf-8') as f:
                json.dump(entities, f, ensure_ascii=False, indent=2)
            # 更新缓存
            EntityConfigManager._cached_entity_map = {code: name for code, name, desc in entities}
            self.last_error = ''
            return True
        except Exception as e:
            # 打包后为窗口程序（无控制台），print 用户不可见：
            # 必须记日志并暴露给 UI，否则表现为"提示保存成功、重开后配置丢失"
            self.last_error = f'写入 {self._entity_file} 失败: {e}'
            logging.error(f"保存发运主体定义失败: {self.last_error}")
            return False

    def get_entity_map(self) -> Dict[str, str]:
        """
        获取发运主体映射（code -> "code-name" 格式）

        Returns:
            发运主体映射字典
        """
        entities = self.load_definitions()
        return {code: f'{code}-{name}' for code, name, desc in entities}

    # ========== 预设管理 ==========

    def load_presets(self) -> Dict:
        """
        加载预设配置

        Returns:
            预设配置字典
        """
        default_config = {
            "presets": {},
            "current_preset": "输送机发运"
        }

        try:
            if self._preset_file.exists():
                with open(self._preset_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logging.error(f"加载预设配置失败: {e}")

        return default_config

    def save_presets(self, config: Dict) -> bool:
        """
        保存预设配置

        Args:
            config: 预设配置字典

        Returns:
            是否保存成功
        """
        try:
            with open(self._preset_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            self.last_error = ''
            return True
        except Exception as e:
            self.last_error = f'写入 {self._preset_file} 失败: {e}'
            logging.error(f"保存预设配置失败: {self.last_error}")
            return False

    def get_preset_names(self) -> List[str]:
        """
        获取所有预设名称

        Returns:
            预设名称列表
        """
        config = self.load_presets()
        return list(config.get('presets', {}).keys())

    def get_current_preset_name(self) -> str:
        """
        获取当前预设名称

        Returns:
            当前预设名称
        """
        config = self.load_presets()
        return config.get('current_preset', '')

    def set_current_preset(self, name: str) -> bool:
        """
        设置当前预设

        Args:
            name: 预设名称

        Returns:
            是否设置成功
        """
        config = self.load_presets()
        config['current_preset'] = name
        return self.save_presets(config)

    def get_preset(self, name: str) -> Optional[Dict]:
        """
        获取指定预设

        Args:
            name: 预设名称

        Returns:
            预设配置，不存在返回 None
        """
        config = self.load_presets()
        return config.get('presets', {}).get(name)

    def save_preset(self, name: str, entities: Dict[str, str]) -> bool:
        """
        保存预设（自动确保锁定代码存在）

        Args:
            name: 预设名称
            entities: 发运主体映射 {code: name}

        Returns:
            是否保存成功
        """
        config = self.load_presets()
        presets = config.get('presets', {})
        # 确保锁定代码存在
        entities_with_locked = EntityConfigManager._ensure_locked_codes(entities)
        presets[name] = {
            'description': f'{name}配置',
            'entities': entities_with_locked
        }
        config['presets'] = presets
        config['current_preset'] = name
        return self.save_presets(config)

    def delete_preset(self, name: str) -> bool:
        """
        删除预设

        Args:
            name: 预设名称

        Returns:
            是否删除成功
        """
        config = self.load_presets()
        presets = config.get('presets', {})

        if name not in presets:
            return False

        if len(presets) <= 1:
            return False  # 至少保留一个预设

        del presets[name]

        # 如果删除的是当前预设，切换到第一个可用预设
        if config.get('current_preset') == name:
            remaining = list(presets.keys())
            if remaining:
                config['current_preset'] = remaining[0]

        config['presets'] = presets
        return self.save_presets(config)

    def create_preset(self, name: str) -> bool:
        """
        创建新预设（默认包含锁定代码）

        Args:
            name: 预设名称

        Returns:
            是否创建成功
        """
        config = self.load_presets()
        presets = config.get('presets', {})

        if name in presets:
            return False  # 已存在

        # 新建预设默认包含锁定代码
        presets[name] = {
            'description': f'{name}配置',
            'entities': EntityConfigManager._get_locked_entities()
        }
        config['presets'] = presets
        return self.save_presets(config)

    def reset_presets(self) -> bool:
        """
        重置预设为默认值

        Returns:
            是否重置成功
        """
        default_entities = {code: name for code, name, desc in self.DEFAULT_ENTITIES}
        default_config = {
            "presets": {
                "输送机发运": {
                    "description": "刮板输送机发运配置",
                    "entities": default_entities
                }
            },
            "current_preset": "输送机发运"
        }
        return self.save_presets(default_config)
