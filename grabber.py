"""
抢课模块
定时选课功能，当前为占位实现
需要用户提供选课API接口地址和参数格式后完善
"""
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class GrabTask:
    """抢课任务"""

    def __init__(self, jxb_id: str, name: str, target_time: datetime, payload: dict | None = None):
        self.jxb_id = jxb_id
        self.name = name
        self.target_time = target_time
        self.payload = payload or {}
        self.status = 'pending'  # pending / running / success / failed
        self.result_msg = ''
        self.created_at = datetime.now()
        self.completed_at: Optional[datetime] = None


class CourseGrabber:
    """
    选课抢课服务
    当前为占位实现，需要用户提供选课API接口后完善
    """

    def __init__(self, config):
        self.config = config
        self._tasks: list[GrabTask] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def schedule_grab(self, jxb_id: str, name: str, target_time: datetime,
                       payload: dict | None = None) -> GrabTask:
        """添加一个定时抢课任务"""
        task = GrabTask(jxb_id=jxb_id, name=name, target_time=target_time, payload=payload or {})
        with self._lock:
            self._tasks.append(task)
        logger.info(f'已添加抢课任务: {name} 于 {target_time}')
        return task

    def remove_task(self, task_id: int) -> bool:
        with self._lock:
            for i, t in enumerate(self._tasks):
                if id(t) == task_id:
                    self._tasks.pop(i)
                    return True
        return False

    def get_tasks(self) -> list[dict]:
        with self._lock:
            return [
                {
                    'id': id(t),
                    'jxb_id': t.jxb_id,
                    'name': t.name,
                    'target_time': t.target_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'status': t.status,
                    'result_msg': t.result_msg,
                    'created_at': t.created_at.strftime('%H:%M:%S'),
                }
                for t in self._tasks
            ]

    def _do_grab(self, task: GrabTask) -> bool:
        """执行选课请求"""
        logger.info(f'正在尝试抢课: {task.name} ({task.jxb_id})')
        url = f'{self.config.base_url}/xsxk/zzxkyzbjk_xkBcZyZzxkYzb.html?gnmkdm=N253512'
        payload = {
            'jxb_ids': task.jxb_id,
            'kch_id': task.payload.get('kch_id', ''),
            'kcmc': task.payload.get('kcmc', f'({task.payload.get("kch_id", "")})抢课'),
            'rwlx': '1', 'rlkz': '0', 'cdrlkz': '0', 'rlzlkz': '1',
            'sxbj': '1', 'xxkbj': '0', 'qz': '0', 'cxbj': '0',
            'xkkz_id': task.payload.get('xkkz_id', self.config.xkkz_id),
            'njdm_id': self.config.njdm_id,
            'zyh_id': self.config.zyh_id,
            'kklxdm': '01', 'xklc': '2',
            'xkxnm': self.config.xkxnm,
            'xkxqm': self.config.xkxqm,
            'jcxx_id': '',
        }
        try:
            import requests
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
            resp = sess.post(url, data=payload, timeout=15)
            if resp.status_code == 200:
                task.result_msg = '选课请求已发送'
                return True
            task.result_msg = f'HTTP {resp.status_code}'
            return False
        except Exception as e:
            task.result_msg = str(e)
            return False

    def _process_task(self, task: GrabTask):
        """处理单个抢课任务"""
        task.status = 'running'
        task.result_msg = '正在执行...'

        # 重试机制：最多尝试30次，间隔2秒
        max_retries = 30
        for attempt in range(1, max_retries + 1):
            if not self._running:
                task.status = 'cancelled'
                return

            success = self._do_grab(task)
            if success:
                task.status = 'success'
                task.result_msg = f'抢课成功！尝试次数: {attempt}'
                task.completed_at = datetime.now()
                return

            logger.info(f'抢课尝试 {attempt}/{max_retries} 失败, 2秒后重试...')
            time.sleep(2)

        task.status = 'failed'
        task.result_msg = f'已达到最大重试次数 ({max_retries})，抢课失败'
        task.completed_at = datetime.now()

    def _run_loop(self):
        """后台线程：检查到时的任务并执行"""
        while self._running:
            now = datetime.now()
            with self._lock:
                pending = [t for t in self._tasks if t.status == 'pending' and t.target_time <= now]

            for task in pending:
                thread = threading.Thread(target=self._process_task, args=(task,), daemon=True)
                thread.start()

            time.sleep(1)

    def start(self):
        if self._running:
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name='GrabberThread')
        self._thread.start()
        return True

    def stop(self):
        self._running = False
