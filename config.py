"""
安全配置管理
从 .env 文件加载敏感配置，避免硬编码在代码中
"""
import os
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """应用配置类"""

    def __init__(self, env_path: str | None = None):
        if env_path is None:
            env_path = Path(__file__).parent / '.env'
        load_dotenv(env_path)

        # Cookies
        self.cookie_jsessionid = os.getenv('COOKIE_JSESSIONID', '')
        self.cookie_route = os.getenv('COOKIE_ROUTE', '')

        # 教务系统
        self.base_url = os.getenv('BASE_URL', 'https://jwxt.shu.edu.cn/jwglxt')


        # 监控参数
        self.class_capacity = int(os.getenv('CLASS_CAPACITY', '30'))
        self.check_interval = int(os.getenv('CHECK_INTERVAL', '30'))

        # 学期参数（当前学年学期，如果查不到课程可以改这个）
        self.xkxnm = os.getenv('XKXNM', '2026')   # 学年 如 2026 = 2026-2027学年
        self.xkxqm = os.getenv('XKXQM', '3')      # 学期码（系统更新后改为3）

        # 用户上下文参数
        self.xh_id = os.getenv('XH_ID', 'B1')
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
        self.xkkz_id = os.getenv('XKKZ_ID', '458F6379768B4061E063F1000A0AC4CD')

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
        }
