'use strict';

(function installMyAivanI18n() {
  const locales = [
    ['en', 'EN', 'English', 'en'], ['zh', '简', '简体中文', 'zh-CN'],
    ['zht', '繁', '繁體中文', 'zh-Hant'], ['fr', 'FR', 'Français', 'fr'],
    ['es', 'ES', 'Español', 'es'], ['de', 'DE', 'Deutsch', 'de'],
    ['ko', '한', '한국어', 'ko'], ['ja', '日', '日本語', 'ja'],
  ];
  const names = Object.fromEntries(locales.map(([code, label, name, htmlLang]) => [code, { label, name, htmlLang }]));
  const en = {
    'myAIVAN 工作台': 'myAIVAN Workbench',
    '登录 myAIVAN': 'Sign in to myAIVAN', '安全登录': 'Secure sign in',
    '访问凭据仅用于换取 HttpOnly 会话，不会保存在浏览器存储中。': 'The access credential is exchanged only for an HttpOnly session and is never stored in browser storage.',
    '部署访问凭据': 'Deployment access credential', '退出': 'Sign out',
    'myAIVAN 首页': 'myAIVAN home', '贸易业务工作台': 'Trade operations workbench',
    '切换业务角色': 'Switch business role', '主导航': 'Main navigation',
    '当前角色': 'Current role', '总览': 'Overview', '业务案例': 'Business cases',
    '录入询盘': 'New inquiry', '人工转发': 'Guided relay', '依赖健康': 'Dependency health',
    '今日业务': 'Today', '运营总览': 'Operations overview', '录入新询盘': 'Record inquiry',
    '最近更新': 'Recent updates', '查看全部': 'View all', '状态筛选': 'Status filter',
    '全部状态': 'All states', '刷新': 'Refresh', '上一页': 'Previous', '下一页': 'Next',
    '← 返回案例': '← Back to cases', '录入买家询盘': 'Record buyer inquiry',
    '买家标识': 'Buyer ID', '买家名称': 'Buyer name', '询盘原文': 'Original inquiry',
    '客户或公司名称': 'Customer or company name',
    '粘贴中文、英文或其他语言的原始询盘…': 'Paste the original inquiry in Chinese, English, or another language…',
    '附件 / 语音': 'Attachments / voice', '创建案例并生成待审批草稿': 'Create case and draft for approval',
    '附件功能状态': 'Attachment feature status',
    '当前候选仅提供元数据占位；对象存储授权与恶意内容扫描未完成前禁止上传。': 'This candidate provides metadata placeholders only. Uploads remain disabled until object-storage authorization and malicious-content scanning are complete.',
    '微信 / 旺旺人工转发': 'WeChat / WangWang guided relay', '发送后的回执编号': 'Receipt reference after relay',
    '确认已人工转发': 'Confirm manual relay', '依赖健康': 'Dependency health',
    'AIVAN 只生成转发卡。必须由人员复制、在目标客户端发送并填写回执，系统不会自动外发个人 IM。': 'AIVAN creates relay cards only. A person must copy, send in the destination client, and enter the receipt; the system never sends personal IM automatically.',
    '此页面只显示配置状态，不主动连接外部依赖，也不替代 CTYun、桥接、备份恢复和真机五轮验收证据。': 'This page shows configuration status only. It does not connect to external dependencies or replace CTYun, bridge, backup-restore, and five-round device evidence.',
    '暂无数据': 'No data', '当前筛选条件下没有可显示的记录。': 'No records match the current filter.',
    '正在读取案例…': 'Loading cases…', '询盘': 'Inquiry', '寻源': 'Sourcing',
    '等待供应商': 'Awaiting supplier', '供应商已回复': 'Supplier replied',
    '等待审批': 'Awaiting approval', '已审批': 'Approved', '质检': 'Quality control',
    '物流': 'Logistics', '完成': 'Completed', '管理员': 'Administrator', '销售': 'Sales',
    '采购': 'Procurement', '跟单': 'Follow-up', '审批人': 'Approver', '审计员': 'Auditor',
    '买家': 'Buyer', '供应商': 'Supplier', '复制': 'Copy', '审批': 'Approve',
    '影响预览': 'Impact preview', '纠错': 'Correct', '导出审计': 'Export audit',
    '已完成': 'Completed', '已取消': 'Cancelled',
    '无法恢复会话，请重新登录。': 'The session could not be restored. Please sign in again.', '登录失败': 'Sign-in failed',
    '已切换为': 'Switched to ', '角色切换失败：': 'Role switch failed: ',
    '冻结候选': 'Frozen candidate', '候选未冻结': 'Candidate not frozen',
    '仅可作为非生产工作台使用。': 'This workbench is for non-production use only.',
    '未命名询盘': 'Unnamed inquiry', '未知客户': 'Unknown customer', '读取案例失败：': 'Could not load cases: ',
    '可见案例': 'Visible cases', '当前角色投影': 'Current role projection', '活跃案例': 'Active cases',
    '本页统计': 'Current page', '需要人工决定': 'Human decision required', '服务器授权': 'Server authorization',
    '正在读取共享 Core 数据…': 'Loading shared Core data…', '需求事实': 'Requirement facts',
    '参与者与角色': 'Participants and roles', '待办与草稿': 'Tasks and drafts',
    '消息证据（仅摘要）': 'Message evidence (digest only)', '回执': 'Receipts',
    '事件时间线': 'Event timeline', '审计记录': 'Audit records', '待审批': 'Pending approval',
    '摘要回执': 'Receipt digest', '案例': 'Case', '已创建': 'created',
    '已进入 Core 工作流': 'Entered the Core workflow', '询盘已写入共享 Core': 'Inquiry recorded in shared Core',
    '创建失败：': 'Creation failed: ', '已审批，等待人工转发': 'Approved; awaiting manual relay',
    '已审批并产生发送回执': 'Approved with a send receipt', '审批完成': 'Approval complete',
    '审批失败：': 'Approval failed: ', '影响范围：': 'Impact scope: ', '预览失败：': 'Preview failed: ',
    '请输入纠错原因。操作将写入不可变审计记录；不物理删除历史。': 'Enter a correction reason. The operation writes an immutable audit record and does not physically delete history.',
    '纠错已应用': 'Correction applied', '已创建补偿任务': 'Compensation task created', '纠错失败：': 'Correction failed: ',
    '正在读取转发队列…': 'Loading relay queue…', '复制内容': 'Copy content',
    '外部消息 ID 或人工回执编号': 'External message ID or manual receipt reference',
    '读取转发队列失败：': 'Could not load the relay queue: ', '已记录 relayed 回执': 'Relayed receipt recorded',
    '确认失败：': 'Confirmation failed: ', '数据库': 'Database', '运行时配置': 'Runtime configuration',
    '只读配置检查': 'Read-only configuration check', '本地模型': 'Local model', '候选版本': 'Candidate version',
    '未冻结': 'Not frozen', '已配置': 'Configured', '待完成': 'Pending',
    '读取健康状态失败：': 'Could not load health status: ', '已复制到剪贴板': 'Copied to clipboard',
  };
  const zht = {
    '登录 myAIVAN': '登入 myAIVAN', '安全登录': '安全登入', '退出': '登出',
    '当前角色': '目前角色', '总览': '總覽', '业务案例': '業務案例', '录入询盘': '錄入詢盤',
    '人工转发': '人工轉發', '依赖健康': '依賴健康', '运营总览': '營運總覽',
    '录入新询盘': '錄入新詢盤', '最近更新': '最近更新', '查看全部': '查看全部',
    '状态筛选': '狀態篩選', '全部状态': '全部狀態', '刷新': '重新整理',
    '上一页': '上一頁', '下一页': '下一頁', '← 返回案例': '← 返回案例',
    '录入买家询盘': '錄入買家詢盤', '买家标识': '買家識別碼', '买家名称': '買家名稱',
    '询盘原文': '詢盤原文', '创建案例并生成待审批草稿': '建立案例並產生待審批草稿',
    '暂无数据': '暫無資料', '询盘': '詢盤', '等待供应商': '等待供應商',
    '供应商已回复': '供應商已回覆', '等待审批': '等待審批', '已审批': '已審批',
    '采购': '採購', '审批人': '審批人', '审计员': '稽核員', '买家': '買家',
    '供应商': '供應商', '复制': '複製', '审批': '審批', '纠错': '糾錯', '导出审计': '匯出稽核',
  };
  const sourceByNode = new WeakMap();
  const generatedCatalogs = {};
  let locale = readLocale();

  function readLocale() {
    const saved = window.localStorage.getItem('myaivan.locale');
    return names[saved] ? saved : 'zh';
  }

  function translate(source) {
    if (locale === 'zh') return source;
    if (locale === 'zht') return zht[source] || source;
    if (locale === 'en') return en[source] || source;
    return generatedCatalogs[locale]?.[source] || en[source] || source;
  }

  function hasGeneratedCatalog(code = locale) {
    return !['fr', 'es', 'de', 'ko', 'ja'].includes(code) || Boolean(generatedCatalogs[code]);
  }

  function apply(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const original = sourceByNode.get(node) || node.nodeValue;
      if (!original || !original.trim()) return;
      sourceByNode.set(node, original);
      const trimmed = original.trim();
      const translated = translate(trimmed);
      if (translated !== trimmed) node.nodeValue = original.replace(trimmed, translated);
      else if (locale === 'zh') node.nodeValue = original;
    });
    document.querySelectorAll('[placeholder]').forEach((node) => {
      const source = node.dataset.i18nPlaceholder || node.getAttribute('placeholder');
      node.dataset.i18nPlaceholder = source;
      node.setAttribute('placeholder', translate(source));
    });
    document.querySelectorAll('[aria-label]:not([data-language]):not(#language-trigger)').forEach((node) => {
      const source = node.dataset.i18nAriaLabel || node.getAttribute('aria-label');
      node.dataset.i18nAriaLabel = source;
      node.setAttribute('aria-label', translate(source));
    });
    document.title = translate('myAIVAN 工作台');
    const generated = hasGeneratedCatalog();
    document.documentElement.lang = generated ? names[locale].htmlLang : 'en';
    const trigger = document.querySelector('#language-trigger');
    if (trigger) {
      trigger.textContent = names[locale].label;
      trigger.setAttribute('aria-label', `${names[locale].name} — Language`);
    }
    document.querySelectorAll('[data-language]').forEach((node) => {
      node.setAttribute('aria-current', node.dataset.language === locale ? 'true' : 'false');
    });
    const status = document.querySelector('#language-status');
    if (status) {
      status.hidden = generated;
      status.textContent = generated ? '' : 'Translation unavailable; showing authoritative English.';
    }
  }

  function setLocale(next) {
    if (!names[next]) return;
    locale = next;
    window.localStorage.setItem('myaivan.locale', next);
    apply();
    window.dispatchEvent(new CustomEvent('myaivan:locale', { detail: { locale } }));
  }

  function bind() {
    const trigger = document.querySelector('#language-trigger');
    const menu = document.querySelector('#language-menu');
    trigger?.addEventListener('click', () => {
      const open = menu.hidden;
      menu.hidden = !open;
      trigger.setAttribute('aria-expanded', String(open));
    });
    menu?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-language]');
      if (!button) return;
      setLocale(button.dataset.language);
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      trigger.focus();
    });
    new MutationObserver((records) => records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) apply(node);
    }))).observe(document.body, { childList: true, subtree: true });
    apply();
  }

  window.myAivanI18n = {
    get locale() { return locale; },
    t: translate,
    setLocale,
    apply,
    installGeneratedCatalog(code, catalog) {
      if (['fr', 'es', 'de', 'ko', 'ja'].includes(code) && catalog && typeof catalog === 'object') {
        generatedCatalogs[code] = Object.freeze({ ...catalog });
        if (locale === code) apply();
      }
    },
    hasGeneratedCatalog,
  };
  document.addEventListener('DOMContentLoaded', bind, { once: true });
}());
