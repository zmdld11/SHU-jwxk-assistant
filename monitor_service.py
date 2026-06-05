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

        # 自动抢课列表: {id: {kch_id, jxb_id, name, xkkz_id, status, jxbmc}}
        self._grab_list: dict[str, dict] = {}
        self._grab_results: dict[str, dict] = {}

        # 抢课回调（由 app.py 注入）
        self.on_auto_grab: Callable | None = None

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
            'txbsfrl': '1',
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
            'sfkxq': '1',
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
            'rlzlkz': '1',
            'kklxdm': '01',
            'kch_id': kch_id,
            'jxbzcxskg': '0',
            'zxgbxkkg': '0',
            'xklc': '2',
            'xkkz_id': self.config.xkkz_id,
            'cxbj': '0',
            'fxbj': '0',
        }

    def _normalize_items(self, items: list[dict], identifier: str) -> list[dict]:
        """统一处理 API 返回的课程数据"""
        for item in items:
            item.setdefault('yxzrs', '0')
            item.setdefault('jxbrl', str(self.config.class_capacity))
            jsxx = item.get('jsxx', '')
            parts = jsxx.split('/')
            teacher_name = parts[1] if len(parts) >= 3 else (parts[-1] if parts else '')
            enrolled = int(item.get('yxzrs', 0))
            cap = int(item.get('zrs', 0)) or int(item.get('jxbrl', self.config.class_capacity))
            item['jxbmc'] = item.get('jxbmc') or identifier
            item['skjs'] = item.get('skjs') or teacher_name
            item['zrs'] = str(cap)
            item['_enrolled'] = enrolled
            item['_capacity'] = cap
            item['_remaining'] = max(0, cap - enrolled)
        return items

    def query_course(self, kch_id: str) -> tuple[list[dict], str | None]:
        """查询指定课程号的所有教学班信息"""
        return self._search(kch_id=kch_id)

    def search_course(self, keyword: str) -> tuple[list[dict], str | None]:
        """按课程名模糊搜索"""
        return self._search(keyword=keyword)

    def _search(self, kch_id: str = '', keyword: str = '') -> tuple[list[dict], str | None]:
        """通用课程搜索"""
        semesters = [('2025', '32'), ('2025', '16'), ('2026', '3')]
        url = f'{self.config.base_url}/xsxk/zzxkyzbjk_cxJxbWithKchZzxkYzb.html?gnmkdm=N253512'

        seen_sem = set()
        for xnm, xqm in semesters:
            key = f'{xnm}_{xqm}'
            if key in seen_sem: continue
            seen_sem.add(key)
            payload = self._build_payload(kch_id or keyword)
            payload['xkxnm'] = xnm
            payload['xkxqm'] = xqm
            # 模糊搜索：filter_list 放关键词，kch_id 放课程号
            if keyword and not kch_id:
                payload['kch_id'] = ''
                payload['filter_list[0]'] = keyword
            try:
                resp = self.session.post(url, data=payload, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    self._normalize_items(data, kch_id or keyword)
                    logger.info(f'搜索成功: 学年={xnm}, 学期={xqm}, 返回 {len(data)} 条')
                    return data, None
                if resp.status_code == 901:
                    logger.warning('HTTP 901 = 会话已过期，请更新 Cookies')
                    break
            except requests.exceptions.RequestException as e:
                logger.error(f'网络请求失败 (xnm={xnm}, xqm={xqm}): {e}')
                continue
            except Exception as e:
                logger.error(f'解析数据失败 (xnm={xnm}, xqm={xqm}): {e}')
                continue
        return [], '无法获取课程数据。Cookies 可能已过期'

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

    # ---- 自动抢课 ----

    def add_grab(self, kch_id: str, jxb_id: str, name: str, xkkz_id: str = '',
                 jxbmc: str = '') -> str:
        """添加自动抢课任务"""
        gid = f'grab_{jxb_id}'
        with self._lock:
            if gid not in self._grab_list:
                self._grab_list[gid] = {
                    'kch_id': kch_id,
                    'jxb_id': jxb_id,
                    'name': name,
                    'xkkz_id': xkkz_id,
                    'jxbmc': jxbmc,
                    'status': '监控中',
                    'attempts': 0,
                }
        return gid

    def remove_grab(self, gid: str) -> bool:
        with self._lock:
            if gid in self._grab_list:
                del self._grab_list[gid]
                self._grab_results.pop(gid, None)
                return True
            return False

    def get_grab_list(self) -> dict:
        with self._lock:
            result = {}
            for gid, info in self._grab_list.items():
                result[gid] = {
                    **info,
                    'latest': self._grab_results.get(gid, {}),
                }
            return result

    def _check_grabs(self):
        """在监控循环中检查自动抢课条件"""
        for gid, info in list(self._grab_list.items()):
            if info['status'] in ('成功', '已取消'):
                continue
            # 查询该课程当前状态
            results, _ = self.query_course(info['kch_id'])
            found = None
            for c in results:
                if c.get('jxb_id') == info['jxb_id']:
                    found = c
                    break
            if not found:
                with self._lock:
                    self._grab_list[gid]['status'] = '课程未找到'
                continue

            enrolled = found.get('_enrolled', 0)
            cap = found.get('_capacity', 30)
            remaining = found.get('_remaining', 0)

            with self._lock:
                self._grab_results[gid] = {
                    'enrolled': enrolled,
                    'capacity': cap,
                    'remaining': remaining,
                }

            if remaining > 0 and self.on_auto_grab:
                # 有空位，触发自动抢课
                with self._lock:
                    self._grab_list[gid]['status'] = '尝试选课...'
                    self._grab_list[gid]['attempts'] += 1
                try:
                    success, msg = self.on_auto_grab(info)
                    with self._lock:
                        if success:
                            self._grab_list[gid]['status'] = '成功'
                        else:
                            self._grab_list[gid]['status'] = f'失败: {msg[:30]}'
                except Exception as e:
                    with self._lock:
                        self._grab_list[gid]['status'] = f'异常: {str(e)[:30]}'

    # ---- 检查逻辑 ----

    def check_all(self) -> dict[str, list[dict]]:
        """检查所有监控项，返回 {watch_id: [class_data, ...]}"""
        results = {}
        for watch_id, info in list(self._watchlist.items()):
            watch_results = []
            if info['type'] == 'course':
                watch_results, _ = self.query_course(info['kch_id'])
            elif info['type'] == 'class':
                all_data = self._last_all_results
                watch_results = [
                    c for c in all_data
                    if c.get('jxb_id') == info.get('jxb_id')
                ]

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
            try:
                if self._watchlist:
                    self.check_all()
                if self._grab_list:
                    self._check_grabs()
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
