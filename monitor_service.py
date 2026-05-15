"""
课程监控服务
支持按课程号监控所有教学班，或按教学班ID监控指定班级
"""
import threading
import time
import logging
from datetime import datetime
from typing import Callable

import requests

logger = logging.getLogger(__name__)


class MonitorService:
    """选课人数监控服务"""

    def __init__(self, config):
        self.config = config
        self._session = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

        # 监控列表: {id: {"type": "course"/"class", "kch_id": ..., "jxb_id": ..., "name": ...}}
        self._watchlist: dict[str, dict] = {}

        # 最新检查结果: {id: {...}}
        self._results: dict[str, list[dict]] = {}

        # 已通知集合
        self._notified: set[str] = set()

        # 通知回调
        self.on_notify: Callable | None = None

        # 最后一次完整检查结果（全部）
        self._last_all_results: list[dict] = []

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def _create_session(self) -> requests.Session:
        sess = requests.Session()
        domain = self.config.base_url.split('://')[1].split('/')[0]
        sess.cookies.set('JSESSIONID', self.config.cookie_jsessionid, domain=domain)
        sess.cookies.set('route', self.config.cookie_route, domain=domain)
        sess.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'{self.config.base_url}/xsxk/zzxkyzb_cxZzxkYzbIndex.html?gnmkdm=N253512&layout=default',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': self.config.base_url.rsplit('/jwglxt', 1)[0],
        })
        return sess

    def _build_payload(self, kch_id: str) -> dict:
        """构建查询请求参数（精确匹配教务系统当前版本）"""
        return {
            'gnmkdm': 'N253512',
            'filter_list[0]': kch_id,
            'rwlx': '1',
            'xkly': '1',
            'bklx_id': '0',
            'sfkkjyxdxnxq': '0',
            'kzkcgs': '0',
            'xqh_id': self.config.xh_id,
            'jg_id': self.config.jg_id,
            'zyh_id': self.config.zyh_id,
            'zyfx_id': self.config.zyfx_id,
            'txbsfrl': '0',
            'njdm_id': self.config.njdm_id,
            'bh_id': self.config.bh_id,
            'xbm': self.config.xbm,
            'xslbdm': self.config.xslbdm,
            'mzm': self.config.mzm,
            'xz': self.config.xz,
            'ccdm': self.config.ccdm,
            'xsbj': self.config.xsbj,
            'sfkknj': '1',
            'gnjkxdnj': '0',
            'sfkkzy': '1',
            'kzybkxy': '0',
            'sfznkx': '0',
            'zdkxms': '0',
            'bhbcyxkjxb': '0',
            'sfkcfx': '1',
            'bbhzxjxb': '0',
            'kkbk': '0',
            'kkbkdj': '0',
            'bklbkcj': '0',
            'xkxnm': self.config.xkxnm,
            'xkxqm': self.config.xkxqm,
            'xkxskcgskg': '0',
            'rlkz': '0',
            'cdrlkz': '0',
            'cxcykclxxskg': '0',
            'rlzlkz': '0',
            'kklxdm': '01',
            'kch_id': kch_id,
            'jxbzcxskg': '0',
            'zxgbxkkg': '0',
            'xklc': '1',
            'xkkz_id': self.config.xkkz_id,
            'cxbj': '0',
            'fxbj': '0',
        }

    def query_course(self, kch_id: str) -> tuple[list[dict], str | None]:
        """查询指定课程号的所有教学班信息
        返回: (results, error_message)
        """
        # 优先用配置文件中的学年学期，再尝试其他可能值
        configured = (self.config.xkxnm, self.config.xkxqm)
        fallbacks = [
            configured,
            ('2026', '3'),   # 2026-2027学年 当前学期（系统更新后新版）
            ('2026', '12'),  # 2026-2027学年 秋季学期
            ('2025', '16'),  # 旧版学期编码
        ]
        # 去重
        seen = set()
        semester_attempts = []
        for xnm, xqm in fallbacks:
            key = f'{xnm}_{xqm}'
            if key not in seen:
                seen.add(key)
                semester_attempts.append((xnm, xqm))

        for xnm, xqm in semester_attempts:
            url = f'{self.config.base_url}/xsxk/zzxkyzbjk_cxJxbWithKchZzxkYzb.html?gnmkdm=N253512'
            payload = self._build_payload(kch_id)
            payload['xkxnm'] = xnm
            payload['xkxqm'] = xqm
            try:
                resp = self.session.post(url, data=payload, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    # 统一字段名（API返回的字段名和代码里用的不一样）
                    for item in data:
                        item.setdefault('yxzrs', '0')
                        item.setdefault('jxbrl', str(self.config.class_capacity))
                        jsxx = item.get('jsxx', '')
                        parts = jsxx.split('/')
                        teacher_name = parts[1] if len(parts) >= 3 else (parts[-1] if parts else '')
                        enrolled = int(item.get('yxzrs', 0))
                        cap = int(item.get('zrs', 0)) or int(item.get('jxbrl', self.config.class_capacity))
                        item['jxbmc'] = item.get('jxbmc') or f'{kch_id}'
                        item['skjs'] = item.get('skjs') or teacher_name
                        item['zrs'] = str(cap)
                        # 监控状态字段
                        item['_enrolled'] = enrolled
                        item['_capacity'] = cap
                        item['_remaining'] = max(0, cap - enrolled)
                    logger.info(f'查询成功: 学年={xnm}, 学期={xqm}, 返回 {len(data)} 条')
                    return data, None

                body = resp.text[:200] if resp.text else '(空)'
                logger.warning(f'查询课程 {kch_id} 失败: HTTP {resp.status_code} (xnm={xnm}, xqm={xqm}), 响应: {body}')
                if resp.status_code == 901:
                    # 901 通常表示会话过期，不需要继续尝试其他学期参数
                    logger.warning('HTTP 901 = 会话已过期，请更新 Cookies')
                    break
            except requests.exceptions.RequestException as e:
                logger.error(f'网络请求失败 (xnm={xnm}, xqm={xqm}): {e}')
                continue
            except Exception as e:
                logger.error(f'解析数据失败 (xnm={xnm}, xqm={xqm}): {e}')
                continue

        return [], '无法获取课程数据。原因：Cookies 已过期或无效\n请重新登录教务系统，按以下步骤操作：\n1. 用浏览器打开 jwxt.shu.edu.cn 并登录\n2. 按 F12 → 网络(Network) → 找到任意请求\n3. 复制请求头中的 Cookie 值（JSESSIONID 和 route）\n4. 粘贴到 .env 文件中'

    # ---- 监控列表管理 ----

    def add_course(self, kch_id: str, name: str = '', jxb_filter: str | None = None) -> str:
        """
        添加课程号监控
        - jxb_filter=None: 监控该课程所有教学班（成组）
        - jxb_filter=jxb_id: 只监控指定教学班（单独）
        """
        watch_id = f'course_{kch_id}_{jxb_filter or "all"}'
        with self._lock:
            if watch_id not in self._watchlist:
                self._watchlist[watch_id] = {
                    'type': 'course',
                    'kch_id': kch_id,
                    'name': name or kch_id,
                    'jxb_filter': jxb_filter,
                }
        # 立即查询并填充结果（不等后台轮询）
        results, _ = self.query_course(kch_id)
        with self._lock:
            if jxb_filter:
                results = [r for r in results if r.get('jxb_id') == jxb_filter]
            self._results[watch_id] = results
        return watch_id

    def get_course_results(self, kch_id: str) -> list[dict]:
        """获取课程的最新查询结果（用于显示后选择加入监控）"""
        results, _ = self.query_course(kch_id)
        return results

    def remove_watch(self, watch_id: str) -> bool:
        """移除监控项"""
        with self._lock:
            if watch_id in self._watchlist:
                del self._watchlist[watch_id]
                self._results.pop(watch_id, None)
                return True
            return False

    def get_watchlist(self) -> dict:
        """获取监控列表及其最新结果"""
        with self._lock:
            result = {}
            for wid, info in self._watchlist.items():
                result[wid] = {
                    **info,
                    'results': self._results.get(wid, []),
                }
            return result

    def clear_watchlist(self):
        with self._lock:
            self._watchlist.clear()
            self._results.clear()
            self._notified.clear()

    # ---- 检查逻辑 ----

    def check_all(self) -> dict[str, list[dict]]:
        """检查所有监控项，返回 {watch_id: [class_data, ...]}"""
        results = {}
        for watch_id, info in list(self._watchlist.items()):
            watch_results = []
            if info['type'] == 'course':
                watch_results = self.query_course(info['kch_id'])
            elif info['type'] == 'class':
                # 需要先通过课程号查询，再过滤
                # 这里简化处理：如果有 kch_id 就用，否则需要提前存储
                all_data = self._last_all_results
                watch_results = [
                    c for c in all_data
                    if c.get('jxb_id') == info.get('jxb_id')
                ]
                # 如果没有缓存数据，尝试用 jxb_id 前几位作为 kch_id 查询
                if not watch_results:
                    pass  # 保留上次结果

            # 计算剩余名额
            for c in watch_results:
                enrolled = int(c.get('yxzrs', 0))
                cap = int(c.get('zrs', self.config.class_capacity))
                c['_enrolled'] = enrolled
                c['_capacity'] = cap
                c['_remaining'] = max(0, cap - enrolled)
                c['_jxbmc'] = c.get('jxbmc', c.get('jxb_id', ''))

            with self._lock:
                self._results[watch_id] = watch_results
                # 缓存所有结果以便按 jxb_id 过滤
                self._last_all_results.extend(
                    c for c in watch_results
                    if c.get('jxb_id') not in {x.get('jxb_id') for x in self._last_all_results}
                )

            results[watch_id] = watch_results

        # 检查空位通知
        self._check_notifications(results)
        return results

    def _check_notifications(self, results: dict[str, list[dict]]):
        """检查是否有新的空位并触发通知"""
        new_available = []
        for watch_id, classes in results.items():
            for cls in classes:
                if cls['_remaining'] > 0:
                    jxb_id = cls.get('jxb_id', '')
                    if jxb_id not in self._notified:
                        new_available.append(cls)

        if new_available and self.on_notify:
            try:
                self.on_notify(new_available)
            except Exception as e:
                logger.error(f'通知回调失败: {e}')

        for cls in new_available:
            self._notified.add(cls.get('jxb_id', ''))

    # ---- 后台线程 ----

    def start(self):
        """启动后台监控线程"""
        if self._running:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name='MonitorThread')
        self._thread.start()
        logger.info('监控服务已启动')
        return True

    def stop(self):
        """停止监控"""
        self._running = False
        logger.info('监控服务已停止')
        return True

    @property
    def is_running(self) -> bool:
        return self._running

    def _run_loop(self):
        while self._running:
            if self._watchlist:
                try:
                    self.check_all()
                except Exception as e:
                    logger.error(f'监控检查异常: {e}')
            time.sleep(self.config.check_interval)

    def get_status_summary(self) -> list[dict]:
        """获取所有监控项的状态摘要（用于前端展示）"""
        summary = []
        for watch_id, info in list(self._watchlist.items()):
            classes = self._results.get(watch_id, [])
            # 如果是单独教学班监控，只显示该教学班
            if info.get('jxb_filter'):
                classes = [c for c in classes if c.get('jxb_id') == info['jxb_filter']]
            item = {
                'id': watch_id,
                'name': info['name'],
                'type': info['type'],
                'kch_id': info.get('kch_id', ''),
                'jxb_filter': info.get('jxb_filter'),
                'classes': [],
            }
            for cls in classes:
                item['classes'].append({
                    'jxb_id': cls.get('jxb_id', ''),
                    'name': cls.get('jxbmc', cls.get('kcmc', '')),
                    'teacher': cls.get('skjs', ''),
                    'room': cls.get('jxcd', ''),
                    'college': cls.get('kkxymc', ''),
                    'campus': cls.get('xqumc', ''),
                    'jxms': cls.get('jxms', ''),
                    'time': cls.get('sksj', ''),
                    'enrolled': cls.get('_enrolled', 0),
                    'capacity': cls.get('_capacity', self.config.class_capacity),
                    'remaining': cls.get('_remaining', 0),
                    'notified': cls.get('jxb_id', '') in self._notified,
                })
            summary.append(item)
        return summary

    @staticmethod
    def get_time() -> str:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
