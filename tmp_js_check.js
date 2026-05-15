
var lastQueryData = null;

// Format time: each time slot on its own line
function fmtTime(s) {
    if (!s || s === '--') return '--';
    return s.replace(/<br\s*\/?>/gi, '<br>');
}

// Toggle monitor with animation
function toggleMonitor() {
    var btn = document.getElementById('toggleBtn');
    var isRunning = btn.getAttribute('data-state') === 'running';

    apiFetch('/api/monitor/' + (isRunning ? 'stop' : 'start'), { method: 'POST' }).then(function(d) {
        if (!d) return;
        showToast(d.message, d.success ? 'success' : 'warning');
        refreshData();
    });
}

// ---- Course Query ----
function queryCourse() {
    var input = document.getElementById('courseIdInput').value.trim();
    if (!input) { showToast('请输入课程号或课程名', 'warning'); return; }

    var btn = document.getElementById('queryBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 查询中...';

    doQuery({kch_id: input});

    function doQuery(payload) {
        apiFetch('/api/monitor/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }).then(function(data) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-search me-1"></i>查询';
            var resultDiv = document.getElementById('courseQueryResult');
            if (!data || !data.success) {
                var msg = (data && data.message) ? data.message.replace(/\n/g, '<br>') : '查询失败';
                resultDiv.innerHTML = '<div class="alert alert-danger py-2 mb-0" style="font-size:13px;">' + msg + '</div>';
                lastQueryData = null; return;
            }
            if (data.count === 0) {
                resultDiv.innerHTML = '<div class="alert alert-warning py-2 mb-0">未找到匹配结果</div>';
                lastQueryData = null;
                return;
            }

        var qKchId = input;
        if (data.classes && data.classes[0] && data.classes[0].kch_id) qKchId = data.classes[0].kch_id;
        lastQueryData = { kch_id: qKchId, classes: data.classes };

        var conflictCount = data.has_schedule ? data.classes.filter(function(c){return c.conflict;}).length : 0;
        var html = '<div class="d-flex justify-content-between align-items-center mb-2">'
            + '<div><small class="text-muted">找到 <strong>' + data.count + '</strong> 个教学班</small>'
            + (conflictCount > 0 ? ' <span class="conflict-tag"><i class="fas fa-exclamation-triangle"></i> ' + conflictCount + '个与课表冲突</span>' : '')
            + '</div>'
            + '<button class="btn btn-success btn-sm" onclick="addAllClasses()">'
            + '<i class="fas fa-layer-group me-1"></i>成组加入监控</button></div>';

        html += '<div class="table-responsive" style="max-height:420px;overflow-y:auto;">'
            + '<table class="table table-course mb-0" style="font-size:13px;"><thead><tr>'
            + '<th style="width:13%">教学班</th><th style="width:13%">上课教师</th>'
            + '<th style="width:22%">上课时间</th><th style="width:12%">开课学院</th>'
            + '<th style="width:7%">校区</th><th style="width:16%">已选/容量</th>'
            + '<th style="width:8%">冲突</th><th style="width:9%">操作</th></tr></thead><tbody>';

        data.classes.forEach(function(c, idx) {
            var enrolled = c.enrolled || 0;
            var cap = c.capacity || 30;
            var pct = cap > 0 ? Math.round((enrolled / cap) * 100) : 0;
            var clsName = c.course_name || input;
            var barCls = pct >= 90 ? 'bg-danger' : (pct >= 70 ? 'bg-warning' : 'bg-success');
            var conflictHtml = c.is_enrolled ? '<span class="badge bg-secondary">已选</span>' : '';
            if (c.conflict && !c.is_enrolled) {
                var names = (c.conflict_with || []).slice(0,2).join(', ');
                conflictHtml += ' <span class="conflict-tag"><i class="fas fa-exclamation-triangle"></i> ' + names + '</span>';
            } else if (!c.is_enrolled) {
                conflictHtml += ' <span style="color:#22c55e;font-size:12px;"><i class="fas fa-check"></i> 无</span>';
            }
            var addBtn = c.is_enrolled
                ? '<span class="text-muted" style="font-size:11px;">已选</span>'
                : '<button class="btn btn-outline-primary btn-sm py-0" onclick="addSingleClass(\''+c.jxb_id+'\',\''+clsName+'\',\''+(c.kch_id||'')+'\')">加入</button>';

            html += '<tr><td><small>' + clsName + '</small></td>'
                + '<td><strong>' + (c.skjs || '--') + '</strong></td>'
                + '<td style="font-size:12px;">' + fmtTime(c.sksj) + '</td>'
                + '<td><small>' + (c.kkxymc || '--') + '</small></td>'
                + '<td><small>' + (c.xqumc || '--') + '</small></td>'
                + '<td><div class="d-flex align-items-center gap-1 flex-wrap">'
                + '<span>' + enrolled + '/' + cap + '</span> '
                + '<div class="progress" style="height:5px;width:40px;flex-shrink:0;">'
                + '<div class="progress-bar ' + barCls + '" style="width:' + pct + '%"></div></div>'
                + '</div></td>'
                + '<td>' + conflictHtml + '</td>'
                + '<td>' + addBtn + '</td></tr>';
        });

        html += '</tbody></table></div>';
        resultDiv.innerHTML = html;
    });
    }  // closes doQuery

// ---- Add to Monitor ----
function addAllClasses() {
    if (!lastQueryData) return;
    var kch = lastQueryData.kch_id;
    // 名称搜索时用第一条数据的 kch_id
    if (lastQueryData.classes && lastQueryData.classes.length && lastQueryData.classes[0].kch_id) {
        kch = lastQueryData.classes[0].kch_id;
    }
    apiFetch('/api/monitor/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: kch, name: kch }),
    }).then(function(data) {
        if (data && data.success) { showToast(data.message, 'success'); refreshData(); }
    });
}

function addSingleClass(jxbId, clsName, cKchId) {
    if (!lastQueryData) return;
    var kch = cKchId || lastQueryData.kch_id;
    apiFetch('/api/monitor/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: kch, name: clsName, jxb_filter: jxbId }),
    }).then(function(data) {
        if (data && data.success) { showToast('已加入教学班 ' + clsName, 'success'); refreshData(); }
    });
}

// ---- Monitor Controls ----
function removeWatch(watchId) {
    apiFetch('/api/monitor/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: watchId }),
    }).then(function(d) {
        if (d && d.success) { showToast(d.message, 'success'); refreshData(); }
    });
}

function updateToggleButton(running) {
    var btn = document.getElementById('toggleBtn');
    if (running) {
        btn.className = 'btn btn-toggle btn-warning';
        btn.innerHTML = '<span class="icon-wrap"><i class="fas fa-pause"></i></span> <span class="btn-text">暂停监控</span>';
        btn.setAttribute('data-state', 'running');
    } else {
        btn.className = 'btn btn-toggle btn-success';
        btn.innerHTML = '<span class="icon-wrap"><i class="fas fa-play"></i></span> <span class="btn-text">启动监控</span>';
        btn.setAttribute('data-state', 'stopped');
    }
}

// ---- Monitor List ----
function refreshData() {
    apiFetch('/api/monitor/status').then(function(data) {
        if (!data) return;
        updateToggleButton(data.running);

        var container = document.getElementById('monitorList');
        var watchlist = data.watchlist || [];

        if (watchlist.length === 0) {
            container.innerHTML = '<div class="empty-state"><i class="fas fa-inbox"></i><p>暂无监控课程</p></div>';
            return;
        }

        var html = '';
        watchlist.forEach(function(w, idx) {
            var cls = w.classes || [];
            var collapseId = 'mc_' + idx;
            var isSingle = !!w.jxb_filter;
            var availCount = isSingle ? 0 : cls.filter(function(c){ return c.remaining > 0; }).length;

            html += '<div class="card mb-2 border monitor-card">'
                + '<div class="card-header py-2 d-flex justify-content-between align-items-center"'
                + ' style="cursor:pointer;" data-bs-toggle="collapse" data-bs-target="#' + collapseId + '">'
                + '<div class="d-flex align-items-center gap-2">'
                + '<i class="fas fa-chevron-right collapse-arrow" style="font-size:11px;color:#999;"></i>'
                + (isSingle ? '<span class="badge bg-info" style="font-size:10px;">单个</span>' : '')
                + '<strong>' + w.name + '</strong>'
                + (cls.length > 0 ? ' <span class="text-muted-small">' + cls.length + '个班</span>' : '')
                + (availCount > 0 ? ' <span class="badge badge-available">' + availCount + '个有空位</span>' : '')
                + (!data.running ? ' <span class="badge bg-secondary">已停止</span>' : '')
                + '</div>'
                + '<button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation();removeWatch(\'' + w.id + '\')" title="移出监控"><i class="fas fa-times"></i></button>'
                + '</div>'
                + '<div class="collapse show" id="' + collapseId + '">'
                + '<div class="card-body p-2">';

            if (cls.length === 0) {
                html += '<p class="text-muted-small mb-0">暂无数据</p>';
            } else {
                html += '<div class="table-responsive">'
                    + '<table class="table table-course mb-0" style="font-size:13px;"><thead><tr>'
                    + '<th style="width:13%">教学班</th><th style="width:14%">上课教师</th>'
                    + '<th style="width:24%">上课时间</th><th style="width:12%">开课学院</th>'
                    + '<th style="width:7%">校区</th><th style="width:16%">已选/容量</th>'
                    + '<th style="width:14%">状态</th></tr></thead><tbody>';

                cls.forEach(function(c, ci) {
                    var pct = c.capacity > 0 ? Math.round((c.enrolled / c.capacity) * 100) : 0;
                    var clsName = w.name + '-' + String(ci + 1).padStart(2, '0');
                    var notifyIcon = c.notified ? ' <i class="fas fa-bell text-primary" title="已通知"></i>' : '';
                    var barCls = pct >= 90 ? 'bg-danger' : (pct >= 70 ? 'bg-warning' : 'bg-success');

                    html += '<tr>'
                        + '<td><small>' + clsName + '</small>' + notifyIcon + '</td>'
                        + '<td><strong>' + (c.teacher || '--') + '</strong></td>'
                        + '<td style="font-size:12px;">' + fmtTime(c.time) + '</td>'
                        + '<td><small>' + (c.college || '--') + '</small></td>'
                        + '<td><small>' + (c.campus || '--') + '</small></td>'
                        + '<td><div class="d-flex align-items-center gap-1">'
                        + '<span>' + c.enrolled + '/' + c.capacity + '</span>'
                        + '<div class="progress" style="height:5px;width:40px;">'
                        + '<div class="progress-bar ' + barCls + '" style="width:' + pct + '%"></div></div></div></td>'
                        + '<td>' + (c.remaining > 0
                            ? '<span class="badge badge-available">有空位 余' + c.remaining + '</span>'
                            : '<span class="badge badge-full">已满 ' + pct + '%</span>')
                        + '</td></tr>';
                });

                html += '</tbody></table></div>';
            }
            html += '</div></div></div>';
        });
        container.innerHTML = html;
    });
}

// Auto refresh
refreshData();
setInterval(refreshData, 5000);
