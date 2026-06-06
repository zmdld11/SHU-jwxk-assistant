"""
安全配置管理
从 .env 文件加载敏感配置，避免硬编码在代码中
支持从教务系统页面自动获取动态参数
"""
import os
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """应用配置类"""

    def __init__(self, env_path: str | None = None):
        if env_path is None:
            env_path = Path(__file__).parent / '.env'
        load_dotenv(env_path, override=True)

        # Cookies
        self.cookie_jsessionid = os.getenv('COOKIE_JSESSIONID', '')
        self.cookie_route = os.getenv('COOKIE_ROUTE', '')

        # 教务系统
        self.base_url = os.getenv('BASE_URL', 'https://jwxt.shu.edu.cn/jwglxt')

        # 监控参数
        self.class_capacity = int(os.getenv('CLASS_CAPACITY', '30'))
        self.check_interval = int(os.getenv('CHECK_INTERVAL', '30'))

        # 学期参数（从 .env 读取，但会被 auto_detect 覆盖）
        self.xkxnm = os.getenv('XKXNM', '')
        self.xkxqm = os.getenv('XKXQM', '')

        # 用户上下文参数（关键！从 .env 读取默认值，但会被 auto_detect 覆盖为实际值）
        # xh_id: 学号（如 24122785），不是校区号！
        self.xh_id = os.getenv('XH_ID', '')
        self.xqh_id = os.getenv('XQH_ID', '')  # 校区号（如 B1）
        self.jg_id = os.getenv('JG_ID', '01080000')
        self.zyh_id = os.getenv('ZYH_ID', '20130809010052')
        self.zyfx_id = os.getenv('ZYFX_ID', 'wfx')
        self.njdm_id = os.getenv('NJDM_ID', '2024')
        self.bh_id = os.getenv('BH_ID', '20242013080901005201')
        self.xbm = os.getenv('XBM', '1')
        self.xslbdm = os.getenv('XSLBDM', '01')
        self.mzm = os.getenv('MZM', '01')
        self.xz = os.getenv('XZ', '4')
        self.ccdm = os.getenv('CCDM', '3')
        self.xsbj = os.getenv('XSBJ', '16')
        self.xkkz_id = os.getenv('XKKZ_ID', '')

        # 从页面动态获取的额外参数
        self.xm = ''           # 姓名
        self.xklc = '2'        # 选课轮次
        self.xklcmc = ''       # 选课轮次名称
        self.kklxdm = '01'     # 课程类型代码
        self.xkxnmc = ''       # 学年名称（如 2025-2026）
        self.xkxqmc = ''       # 学期名称（如 夏）

    @property
    def cookies(self) -> dict:
        return {
            'JSESSIONID': self.cookie_jsessionid,
            'route': self.cookie_route,
        }

    def validate(self) -> list[str]:
        """验证配置，返回缺失的必要字段列表"""
        missing = []
        if not self.cookie_jsessionid or self.cookie_jsessionid == '你的JSESSIONID':
            missing.append('COOKIE_JSESSIONID (请从浏览器获取)')
        if not self.cookie_route or self.cookie_route == '你的route值':
            missing.append('COOKIE_ROUTE (请从浏览器获取)')
        return missing

    def to_dict(self) -> dict:
        """返回安全配置字典（隐藏敏感信息）"""
        return {
            'class_capacity': self.class_capacity,
            'check_interval': self.check_interval,
            'base_url': self.base_url,
            'has_jsessionid': bool(self.cookie_jsessionid),
            'has_route': bool(self.cookie_route),
            'xkxnm': self.xkxnm,
            'xkxqm': self.xkxqm,
            'xkxnmc': self.xkxnmc,
            'xkxqmc': self.xkxqmc,
            'xklc': self.xklc,
            'xklcmc': self.xklcmc,
        }

    def update_from_page(self, page_params: dict):
        """从教务系统页面隐藏字段更新配置（以页面值为准，总是覆盖）"""
        mappings = {
            'xkxnm': 'xkxnm',
            'xkxqm': 'xkxqm',
            'xh_id': 'xh_id',
            'xqh_id': 'xqh_id',
            'jg_id_1': 'jg_id',
            'zyh_id': 'zyh_id',
            'zyfx_id': 'zyfx_id',
            'njdm_id': 'njdm_id',
            'bh_id': 'bh_id',
            'xbm': 'xbm',
            'xslbdm': 'xslbdm',
            'mzm': 'mzm',
            'xz': 'xz',
            'ccdm': 'ccdm',
            'xsbj': 'xsbj',
            'xkkz_id': 'xkkz_id',
            'firstXkkzId': 'xkkz_id',
            'xklc': 'xklc',
            'xklcmc': 'xklcmc',
            'kklxdm': 'kklxdm',
            'xkxnmc': 'xkxnmc',
            'xkxqmc': 'xkxqmc',
            'xkkssj': 'xkkssj',
            'xkjssj': 'xkjssj',
            'xm': 'xm',
        }
        updated = []
        for page_key, attr_name in mappings.items():
            if page_key in page_params and page_params[page_key]:
                old_val = getattr(self, attr_name, '')
                new_val = page_params[page_key]
                # 总是更新，以页面值为准
                if old_val != new_val:
                    updated.append(f'{attr_name}: {old_val} -> {new_val}')
                setattr(self, attr_name, new_val)
        return updated
