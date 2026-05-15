"""
选课监控系统 - Web 主应用
"""
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from config import Config
from monitor_service import MonitorService
from grabber import CourseGrabber

# 配置日志（控制台 + 文件，每次启动清空旧日志）
LOG_FILE = Path(__file__).parent / 'app.log'
LOG_FILE.write_text('', encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
# 单独添加文件 handler
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
logging.getLogger().addHandler(fh)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'jwxk-monitor-secret-key-change-in-production'


# ==================== CORS 支持 ====================
@app.after_request
def add_cors_headers(response):
    """允许来自教务系统页面的跨域请求（供书签工具使用）"""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# 全局实例
config = Config()
monitor = MonitorService(config)
grabber = CourseGrabber(config)

# 已选课表缓存
_schedule_cache: list[dict] = []  # [{day, start, end, weeks, name, kch_id, jxb_id}]
WATCHLIST_FILE = Path(__file__).parent / 'watchlist.json'


def load_schedule_cache() -> bool:
    """加载课表到缓存（app启动时 + 手动刷新）"""
    global _schedule_cache
    try:
        url = f'{config.base_url}/kbcx/xskbcx_cxXsgrkb.html?gnmkdm=N2151'
        payload = {'xnm': config.xkxnm, 'xqm': config.xkxqm, 'kzlx': 'ck',
                   'xsdm': '', 'kclbdm': '', 'kclxdm': ''}
        resp = monitor.session.post(url, data=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            _schedule_cache = []
            for item in data.get('kbList', []):
                ps = item.get('jcs', '')
                start = int(ps.split('-')[0]) if '-' in ps else 0
                end = int(ps.split('-')[1]) if '-' in ps else 0
                _schedule_cache.append({
                    'day': int(item.get('xqj', 0)),
                    'start': start, 'end': end,
                    'weeks': parse_weeks(item.get('zcd', '')),
                    'name': item.get('kcmc', ''),
                    'kch_id': item.get('kch', '') or item.get('kch_id', ''),
                    'jxb_id': item.get('jxb_id', ''),
                })
            logger.info(f'课表已预加载: {len(_schedule_cache)} 条')
            return True
        logger.warning(f'课表预加载失败: HTTP {resp.status_code}')
        return False
    except Exception as e:
        logger.warning(f'课表预加载异常: {e}')
        return False


def load_watchlist():
    """从文件加载监控列表"""
    if not WATCHLIST_FILE.exists():
        return
    try:
        data = json.loads(WATCHLIST_FILE.read_text('utf-8'))
        for item in data:
            kch_id = item.get('kch_id', '')
            jxb_filter = item.get('jxb_filter')
            if kch_id:
                monitor.add_course(kch_id, item.get('name', kch_id), jxb_filter=jxb_filter)
        logger.info(f'监控列表已恢复: {len(data)} 项')
    except Exception as e:
        logger.warning(f'读取监控列表失败: {e}')


def save_watchlist():
    """保存监控列表到文件"""
    try:
        items = []
        for wid, info in monitor._watchlist.items():
            items.append({
                'kch_id': info.get('kch_id', ''),
                'name': info.get('name', ''),
                'jxb_filter': info.get('jxb_filter'),
            })
        WATCHLIST_FILE.write_text(json.dumps(items, ensure_ascii=False), 'utf-8')
    except Exception as e:
        logger.warning(f'保存监控列表失败: {e}')


# ==================== 时间/周次解析 ====================

WEEKDAY_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 7}


def parse_weeks(week_str: str) -> set[int]:
    """解析周次字符串，返回周编号集合
    支持: '1-8周', '9-16周', '2-16周(双)', '1,5,9,13周', '9-15周(单)'
    """
    if not week_str:
        return set()
    week_str = week_str.replace('周', '').strip()
    odd = '(单)' in week_str or '(奇)' in week_str
    even = '(双)' in week_str or '(偶)' in week_str
    week_str = re.sub(r'\(.*?\)', '', week_str).strip()
    weeks = set()
    for part in week_str.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                for w in range(int(a), int(b) + 1):
                    weeks.add(w)
            except ValueError:
                continue
        else:
            try:
                weeks.add(int(part))
            except ValueError:
                continue
    if odd:
        weeks = {w for w in weeks if w % 2 == 1}
    if even:
        weeks = {w for w in weeks if w % 2 == 0}
    return weeks


def parse_sksj_time(sksj: str) -> list[dict]:
    """解析查询API返回的sksj字段
    支持格式: '星期二第3-4节{1-8周}' 或 '周一3-4节{1-8周}'
    """
    if not sksj:
        return []
    results = []
    DAY_MAP = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 7}
    text = sksj.replace('<br/>', '\n').replace('<br>', '\n')
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        # 找星期X: 可能是 "星期X" 或 "周X"
        day = 0
        rest_start = 0
        # 先试 "星期X"
        idx_week = line.find('星期')
        if idx_week >= 0 and idx_week + 2 < len(line):
            day = DAY_MAP.get(line[idx_week + 2], 0)
            rest_start = idx_week + 3
        else:
            # 再试 "周X"
            idx_z = line.find('周')
            if idx_z >= 0 and idx_z + 1 < len(line):
                day = DAY_MAP.get(line[idx_z + 1], 0)
                rest_start = idx_z + 2
        if not day:
            continue
        # 跳过可选的 "第" 字符
        if rest_start < len(line) and line[rest_start] == '第':
            rest_start += 1
        rest = line[rest_start:]
        m = re.search(r'(\d+)\s*[-–—]\s*(\d+)节?', rest)
        if not m:
            continue
        start, end = int(m.group(1)), int(m.group(2))
        brace = re.search(r'\{([^}]+)\}', line)
        weeks = parse_weeks(brace.group(1)) if brace else set(range(1, 17))
        results.append({'day': day, 'start': start, 'end': end, 'weeks': weeks})
    return results


def check_conflict(schedule_slots: list[dict], course_slots: list[dict]) -> list[dict]:
    """检测时间冲突
    返回冲突的时间段列表
    """
    conflicts = []
    for ss in schedule_slots:
        for cs in course_slots:
            if ss['day'] != cs['day']:
                continue
            # 时间段重叠
            if cs['start'] > ss['end'] or cs['end'] < ss['start']:
                continue
            # 周次有交集
            if ss.get('weeks') and cs.get('weeks'):
                if not (ss['weeks'] & cs['weeks']):
                    continue
            conflicts.append(cs)
            break  # 此课程时间段已冲突，跳出内层循环
        if cs in conflicts:
            break  # 已标记，检查下一个
    return conflicts


# ==================== 页面路由 ====================

@app.route('/')
def index():
    return render_template('index.html',
                         config=config.to_dict(),
                         running=monitor.is_running,
                         watch_count=len(monitor._watchlist) if hasattr(monitor, '_watchlist') else 0)


@app.route('/monitor')
def monitor_page():
    return render_template('monitor.html', config=config.to_dict())


@app.route('/grab')
def grab_page():
    return render_template('grab.html', config=config.to_dict())


@app.route('/schedule')
def schedule_page():
    return render_template('schedule.html', config=config.to_dict())


@app.route('/settings')
def settings_page():
    return render_template('settings.html', config=config.to_dict())


# ==================== 监控 API ====================

@app.route('/api/monitor/start', methods=['POST'])
def api_monitor_start():
    if monitor.start():
        return jsonify({'success': True, 'message': '监控已启动'})
    return jsonify({'success': False, 'message': '监控已在运行中'})


@app.route('/api/monitor/stop', methods=['POST'])
def api_monitor_stop():
    monitor.stop()
    return jsonify({'success': True, 'message': '监控已停止'})


@app.route('/api/monitor/status')
def api_monitor_status():
    summary = monitor.get_status_summary()
    return jsonify({
        'running': monitor.is_running,
        'watchlist': summary,
        'current_time': monitor.get_time(),
    })


@app.route('/api/monitor/add', methods=['POST'])
def api_monitor_add():
    data = request.get_json()
    kch_id = data.get('id', '')
    name = data.get('name', '')
    jxb_filter = data.get('jxb_filter')  # 可选：单独教学班ID

    if not kch_id:
        return jsonify({'success': False, 'message': '请输入课程号'})

    result_id = monitor.add_course(kch_id, name or kch_id, jxb_filter=jxb_filter)
    save_watchlist()
    # 查找刚添加的监控项
    summary = monitor.get_status_summary()
    item = next((w for w in summary if w['id'] == result_id), None)
    if item and item.get('classes'):
        cls_list = item['classes']
        msg = f'已添加教学班监控' if jxb_filter else f'已添加课程监控，{len(cls_list)} 个教学班'
        return jsonify({
            'success': True,
            'message': msg,
            'count': len(cls_list),
            'classes': cls_list,
        })
    return jsonify({
        'success': True,
        'message': f'已添加',
        'count': 0,
    })


@app.route('/api/monitor/remove', methods=['POST'])
def api_monitor_remove():
    data = request.get_json()
    watch_id = data.get('id', '')
    if monitor.remove_watch(watch_id):
        save_watchlist()
        return jsonify({'success': True, 'message': '已移除监控'})
    return jsonify({'success': False, 'message': '未找到该监控项'})


@app.route('/api/monitor/check', methods=['POST'])
def api_monitor_check():
    """立即执行一次检查"""
    results = monitor.check_all()
    return jsonify({
        'success': True,
        'results': monitor.get_status_summary(),
        'time': monitor.get_time(),
    })


@app.route('/api/monitor/query', methods=['POST'])
def api_monitor_query():
    """查询指定课程号的数据（不添加到监控），用于预览"""
    data = request.get_json()
    kch_id = data.get('kch_id', '')
    if not kch_id:
        return jsonify({'success': False, 'message': '请输入课程号'})
    results, error = monitor.query_course(kch_id)
    if error and not results:
        return jsonify({'success': False, 'message': error, 'count': 0})

    # 冲突检测 + 课程名查找
    has_schedule = len(_schedule_cache) > 0
    enrolled_jxbs = {ss.get('jxb_id', '') for ss in _schedule_cache}
    enrolled_kchs = {ss.get('kch_id', '') for ss in _schedule_cache if ss.get('kch_id')}
    # 从课表中查找这个课程的名称
    course_name = kch_id
    for ss in _schedule_cache:
        if ss.get('kch_id', '') == kch_id:
            course_name = ss.get('name', kch_id)
            break

    def make_class_item(c):
        sksj = c.get('sksj', '')
        course_slots = parse_sksj_time(sksj) if sksj else []
        conflict_times = []
        is_enrolled = c.get('jxb_id', '') in enrolled_jxbs or kch_id in enrolled_kchs
        if is_enrolled:
            conflict_times.append('已选')
        if has_schedule and course_slots:
            for cs in course_slots:
                for ss in _schedule_cache:
                    if cs['day'] == ss['day'] and not (cs['end'] < ss['start'] or cs['start'] > ss['end']):
                        if cs.get('weeks') and ss.get('weeks'):
                            if cs['weeks'] & ss['weeks']:
                                conflict_times.append(ss['name'])
                                break
                        elif not cs.get('weeks') or not ss.get('weeks'):
                            conflict_times.append(ss['name'])
                            break

        return {
            'jxb_id': c.get('jxb_id'),
            'course_name': course_name,
            'kch_id': kch_id,
            'skjs': c.get('skjs'),
            'sksj': sksj,
            'kkxymc': c.get('kkxymc', ''),
            'xqumc': c.get('xqumc', ''),
            'jxms': c.get('jxms', ''),
            'enrolled': int(c.get('yxzrs', 0)),
            'capacity': int(c.get('zrs', str(config.class_capacity))),
            'remaining': int(c.get('zrs', str(config.class_capacity))) - int(c.get('yxzrs', '0')),
            'conflict': len(conflict_times) > 0,
            'conflict_with': conflict_times[:3],
            'is_enrolled': is_enrolled,
        }

    return jsonify({
        'success': True,
        'count': len(results),
        'has_schedule': has_schedule,
        'classes': [make_class_item(c) for c in results],
    })


# ==================== 课程搜索 API ====================

@app.route('/api/monitor/search', methods=['POST'])
def api_monitor_search():
    """按名称搜索（不支持，API 只能用课程号查）"""
    return jsonify({'success': False, 'message': '教务系统不支持名称搜索，请输入课程号查询', 'count': 0})


# ==================== 已选课程 API ====================

@app.route('/api/enrolled')
def api_enrolled():
    """获取已选课程列表（从课表缓存读取）"""
    if not _schedule_cache:
        load_schedule_cache()
    # 去重并收集 kch_id 和 jxb_id
    enrolled_set = set()
    courses = []
    for ss in _schedule_cache:
        key = f"{ss.get('kch_id', '')}_{ss.get('jxb_id', '')}"
        if key not in enrolled_set:
            enrolled_set.add(key)
            if ss.get('name'):
                courses.append({
                    'kcmc': ss.get('name', ''),
                    'kch_id': ss.get('kch_id', ''),
                    'jxb_id': ss.get('jxb_id', ''),
                })
    return jsonify({'success': True, 'count': len(courses), 'courses': courses})


# ==================== 抢课 API ====================

@app.route('/api/grab/schedule', methods=['POST'])
def api_grab_schedule():
    data = request.get_json()
    jxb_id = data.get('jxb_id', '')
    kch_id = data.get('kch_id', '')
    name = data.get('name', '') or kch_id or jxb_id
    target_str = data.get('target_time', '')

    if not jxb_id or not target_str:
        return jsonify({'success': False, 'message': '请填写教学班ID和目标时间'})

    try:
        target_time = datetime.strptime(target_str, '%Y-%m-%d %H:%M')
    except ValueError:
        return jsonify({'success': False, 'message': '时间格式错误，请使用 YYYY-MM-DD HH:MM'})

    if target_time <= datetime.now():
        return jsonify({'success': False, 'message': '目标时间必须在当前时间之后'})

    task = grabber.schedule_grab(
        jxb_id, name or jxb_id, target_time,
        payload={'kch_id': kch_id, 'xkkz_id': config.xkkz_id}
    )
    return jsonify({
        'success': True,
        'message': f'已安排抢课任务: {name or jxb_id} 于 {target_str}',
        'task_id': id(task),
    })


@app.route('/api/grab/tasks')
def api_grab_tasks():
    return jsonify({'tasks': grabber.get_tasks()})


@app.route('/api/grab/remove', methods=['POST'])
def api_grab_remove():
    data = request.get_json()
    task_id = data.get('task_id', 0)
    if grabber.remove_task(task_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '未找到该任务'})


# ==================== 退课 API ====================

@app.route('/api/drop', methods=['POST'])
def api_drop():
    """直接退课"""
    data = request.get_json()
    kch_id = data.get('kch_id', '')
    jxb_ids = data.get('jxb_ids', '')

    if not kch_id or not jxb_ids:
        return jsonify({'success': False, 'message': '请输入课程号和教学班ID'})

    url = f'{config.base_url}/xsxk/zzxkyzb_tuikBcZzxkYzb.html?gnmkdm=N253512'
    payload = {
        'kch_id': kch_id,
        'jxb_ids': jxb_ids,
        'xkxnm': config.xkxnm,
        'xkxqm': config.xkxqm,
        'txbsfrl': '1',
    }

    try:
        resp = monitor.session.post(url, data=payload, timeout=10)
        logger.info(f'退课请求: HTTP {resp.status_code}')
        if resp.status_code == 200:
            try:
                result = resp.json()
                # 退课成功后刷新课表缓存
                load_schedule_cache()
                return jsonify({'success': True, 'message': '退课成功', 'detail': result})
            except:
                load_schedule_cache()
                return jsonify({'success': True, 'message': '退课请求已发送', 'detail': resp.text[:200]})
        return jsonify({'success': False, 'message': f'退课失败 HTTP {resp.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'网络错误: {str(e)}'})


# ==================== 选课 API ====================

@app.route('/api/grab/add', methods=['POST'])
def api_grab_add():
    """立即选课（直接调用教务系统选课接口）"""
    import re

    data = request.get_json()
    jxb_ids = data.get('jxb_ids', '')
    kch_id = data.get('kch_id', '')
    kcmc = data.get('kcmc', '')
    xkkz_id = data.get('xkkz_id', config.xkkz_id)

    if not jxb_ids or not kch_id:
        return jsonify({'success': False, 'message': '请输入课程号和教学班ID'})

    if not kcmc:
        kcmc = f'({kch_id}) - 选课'

    # Step 1: 预检（cxXkTitleMsg）— 与浏览器行为一致
    pre_url = f'{config.base_url}/xsxk/zzxkyzb_cxXkTitleMsg.html?gnmkdm=N253512'
    pre_payload = {
        'jxb_ids': jxb_ids, 'xkxnm': config.xkxnm, 'xkxqm': config.xkxqm,
        'bj': '7', 'kch_id': kch_id,
        'njdm_id': config.njdm_id, 'zyh_id': config.zyh_id, 'kklxdm': '01',
    }
    try:
        pre_resp = monitor.session.post(pre_url, data=pre_payload, timeout=10)
        if pre_resp.status_code == 200:
            try:
                pre_result = pre_resp.json()
                if isinstance(pre_result, dict) and pre_result.get('flag') == '0':
                    return jsonify({'success': False, 'message': pre_result.get('msg', '预检未通过，可能不在选课时段内')})
            except:
                pass
        # 即使预检失败也尝试正式选课
    except Exception as e:
        logger.warning(f'选课预检异常: {e}')

    # Step 2: 正式选课
    url = f'{config.base_url}/xsxk/zzxkyzbjk_xkBcZyZzxkYzb.html?gnmkdm=N253512'
    payload = {
        'jxb_ids': jxb_ids, 'kch_id': kch_id, 'kcmc': kcmc,
        'rwlx': '1', 'rlkz': '0', 'cdrlkz': '0', 'rlzlkz': '1',
        'sxbj': '1', 'xxkbj': '0', 'qz': '0', 'cxbj': '0',
        'xkkz_id': xkkz_id, 'njdm_id': config.njdm_id, 'zyh_id': config.zyh_id,
        'kklxdm': '01', 'xklc': '2',
        'xkxnm': config.xkxnm, 'xkxqm': config.xkxqm, 'jcxx_id': '',
    }
    try:
        resp = monitor.session.post(url, data=payload, timeout=15)
        logger.info(f'选课请求: HTTP {resp.status_code}')
        txt = resp.text
        if resp.status_code == 200:
            try:
                result = resp.json()
                if isinstance(result, dict) and result.get('flag') == '0':
                    return jsonify({'success': False, 'message': result.get('msg', '选课失败')})
                # 选课成功后刷新课表缓存
                load_schedule_cache()
                return jsonify({'success': True, 'message': '选课成功！请刷新教务系统页面确认', 'detail': result})
            except:
                pass
            return jsonify({'success': True, 'message': '选课请求已发送，请刷新确认', 'detail': txt[:200]})
        return jsonify({'success': False, 'message': f'选课失败 HTTP {resp.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'网络错误: {str(e)}'})


# ==================== 配置 API ====================

@app.route('/api/config')
def api_config():
    return jsonify(config.to_dict())


@app.route('/api/config/validate')
def api_config_validate():
    missing = config.validate()
    return jsonify({
        'valid': len(missing) == 0,
        'missing': missing,
        'message': '配置完整' if len(missing) == 0 else f'缺少必要配置: {", ".join(missing)}',
    })


# ==================== 配置更新 API ====================

@app.route('/api/update_cookies', methods=['POST'])
def api_update_cookies():
    """
    从浏览器接收 Cookies。支持多种格式：
    1. "JSESSIONID=xxx; route=xxx"  (标准 Cookie 字符串)
    2. {"JSESSIONID": "xxx", "route": "xxx"}  (JSON 对象)
    """
    import re

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '未收到数据'})

    updated = {}

    # 从字符串解析 key=value 对
    raw_val = data.get('cookies', '') or data.get('raw', '')
    if isinstance(raw_val, str):
        for m in re.finditer(r'(JSESSIONID|route)\s*=\s*([^\s;]+)', raw_val, re.IGNORECASE):
            updated[m.group(1).upper()] = m.group(2)

    # 也支持直接传键值对
    for key in ('JSESSIONID', 'route'):
        if key in data:
            updated[key] = str(data[key])
        if key.upper() in data:
            updated[key.upper()] = str(data[key.upper()])

    if not updated:
        return jsonify({'success': False, 'message': '未找到 JSESSIONID 或 route'})

    # 更新 .env
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        return jsonify({'success': False, 'message': '.env 文件不存在'})

    content = env_path.read_text('utf-8')
    for key, value in updated.items():
        k = f'COOKIE_{key.upper()}'
        if re.search(rf'^{k}=', content, re.MULTILINE):
            content = re.sub(rf'^{k}=.*', f'{k}={value}', content, flags=re.MULTILINE)
        else:
            content += f'{k}={value}\n'

    env_path.write_text(content, 'utf-8')

    # 重新加载
    global config, monitor
    config = Config()
    monitor.config = config
    monitor._session = None

    logger.info(f'Cookies 已更新: {", ".join(updated.keys())}')

    return jsonify({
        'success': True,
        'message': f'已更新: {", ".join(updated.keys())}',
        'updated': list(updated.keys()),
    })


@app.route('/api/config/update', methods=['POST'])
def api_config_update():
    """更新 .env 中的配置项"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': '请提供配置项'})

    # 字段名映射 (前端字段名 -> .env 键名)
    field_map = {
        'xkxnm': 'XKXNM',
        'xkxqm': 'XKXQM',
        'check_interval': 'CHECK_INTERVAL',
        'class_capacity': 'CLASS_CAPACITY',
        'xkkz_id': 'XKKZ_ID',
        'jg_id': 'JG_ID',
        'zyh_id': 'ZYH_ID',
        'bh_id': 'BH_ID',
        'njdm_id': 'NJDM_ID',
    }

    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        return jsonify({'success': False, 'message': '.env 文件不存在'})

    lines = env_path.read_text('utf-8').splitlines()
    updated_keys = []

    for field, env_key in field_map.items():
        if field in data and data[field] is not None:
            new_value = str(data[field]).strip()
            found = False
            new_lines = []
            for line in lines:
                if line.strip().startswith(f'{env_key}='):
                    if not found:
                        new_lines.append(f'{env_key}={new_value}')
                        found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f'{env_key}={new_value}')
            lines = new_lines
            updated_keys.append(env_key)

    env_path.write_text('\n'.join(lines) + '\n', 'utf-8')

    # 重新加载配置
    global config
    config = Config()

    return jsonify({
        'success': True,
        'message': f'已更新: {", ".join(updated_keys)}',
        'updated': updated_keys,
    })


# ==================== 课表查询 API ====================

@app.route('/api/schedule')
def api_schedule():
    """查询当前学生的个人课表"""
    # 重新从 API 获取完整数据（包含教师、教室、周次等）
    url = f'{config.base_url}/kbcx/xskbcx_cxXsgrkb.html?gnmkdm=N2151'
    payload = {'xnm': config.xkxnm, 'xqm': config.xkxqm, 'kzlx': 'ck',
               'xsdm': '', 'kclbdm': '', 'kclxdm': ''}
    try:
        resp = monitor.session.post(url, data=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            global _schedule_cache
            _schedule_cache = []
            courses = []
            for item in data.get('kbList', []):
                ps = item.get('jcs', '')
                start = int(ps.split('-')[0]) if '-' in ps else 0
                end = int(ps.split('-')[1]) if '-' in ps else 0
                _schedule_cache.append({
                    'day': int(item.get('xqj', 0)), 'start': start, 'end': end,
                    'weeks': parse_weeks(item.get('zcd', '')),
                    'name': item.get('kcmc', ''),
                    'kch_id': item.get('kch', '') or item.get('kch_id', ''),
                    'jxb_id': item.get('jxb_id', ''),
                })
                courses.append({
                    'kcmc': item.get('kcmc', ''),
                    'kch': item.get('kch', ''),
                    'jxbmc': item.get('jxbmc', ''),
                    'jxb_id': item.get('jxb_id', ''),
                    'teacher': item.get('xm', ''),
                    'zcmc': item.get('zcmc', ''),
                    'room': item.get('cdmc', ''),
                    'room_type': item.get('cdlbmc', ''),
                    'weekday': item.get('xqjmc', ''),
                    'weekday_num': item.get('xqj', 0),
                    'period': item.get('jc', ''),
                    'period_simple': ps,
                    'weeks': item.get('zcd', ''),
                    'credit': item.get('xf', ''),
                })
            return jsonify({'success': True, 'count': len(courses), 'courses': courses})
        return jsonify({'success': False, 'message': f'请求失败 HTTP {resp.status_code}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})



# ==================== 启动 ====================

def main():
    # 检查配置
    missing = config.validate()
    if missing:
        logger.warning(f'配置不完整: {", ".join(missing)}')
        logger.warning('请复制 .env.example 为 .env 并填写配置')
    else:
        logger.info('配置验证通过')
        # 预加载课表和监控列表（仅配置完整时）
        load_schedule_cache()
        load_watchlist()

    # 启动抢课后台线程
    grabber.start()

    logger.info('=' * 40)
    logger.info('选课监控系统 Web 界面启动')
    logger.info(f'访问地址: http://127.0.0.1:5000')
    logger.info('=' * 40)

    app.run(debug=True, host='127.0.0.1', port=5000, use_reloader=False)


if __name__ == '__main__':
    main()
