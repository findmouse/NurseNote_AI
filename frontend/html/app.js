/*
 * NurseNote AI - フロントエンド（M1）
 *
 * ビルドツールも外部ライブラリも使わない。
 *  - 画面の状態と描画 … Vue 3（Options API、グローバルビルド）
 *  - HTTP 通信       … ブラウザ標準の fetch API
 *
 * fetch は Vue とは無関係にブラウザが元から持っている機能なので、
 * 通信用のライブラリを別途読み込む必要はない。ただし癖が 2 つある。
 *   1. 404 や 500 でも「通信は成功した」扱いになる → res.ok を自分で確認する
 *   2. 戻り値は生のレスポンス → res.json() で中身を取り出す
 * これらをすべて下の api() に閉じ込めてあるので、各メソッドからは
 * `await api('GET', '/patients')` と書くだけでよい。
 */

const API = '/api/v1';
const TOKEN_KEY = 'nursenote_token';

/** API がエラーを返したときに投げる例外。status と日本語メッセージを持つ。 */
class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** FastAPI のエラー応答 {detail: ...} からメッセージを取り出す */
function extractDetail(data) {
  if (!data || typeof data !== 'object') return null;
  const d = data.detail;
  if (typeof d === 'string') return d;
  if (d) return JSON.stringify(d); // バリデーションエラーは配列で返る
  return null;
}

/**
 * 認証ヘッダー付きの fetch。
 * @param {string} method  'GET' | 'POST' など
 * @param {string} path    '/patients' のような API パス
 * @param {object} [opt]   { params: クエリ文字列, body: JSON ボディ }
 * @returns {Promise<any>} パース済みのレスポンス
 * @throws  {ApiError}     HTTP エラー時
 */
async function api(method, path, opt = {}) {
  const url = new URL(API + path, window.location.origin);
  if (opt.params) {
    for (const [key, value] of Object.entries(opt.params)) {
      // 未入力の項目はクエリに含めない
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, value);
      }
    }
  }

  const headers = {};
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.Authorization = 'Bearer ' + token;
  if (opt.body !== undefined) headers['Content-Type'] = 'application/json; charset=utf-8';

  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: opt.body !== undefined ? JSON.stringify(opt.body) : undefined,
    });
  } catch (e) {
    // ネットワーク到達不可（サーバー停止など）
    throw new ApiError(0, 'サーバーに接続できません');
  }

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (e) {
      data = text;
    }
  }

  if (!res.ok) {
    throw new ApiError(
      res.status,
      extractDetail(data) || `通信に失敗しました（HTTP ${res.status}）`
    );
  }
  return data;
}

/** yyyy-mm-dd 形式の今日 */
function emptyGenMeta() {
  return { model_name: null, prompt_version: null, token_usage: null };
}

/** 根拠テキストを本文に重ねて、色分け用の断片に分ける。 */
function buildPreview(text, evidence) {
  if (!text) return [];
  const ranges = [];
  for (const item of evidence || []) {
    if (!item || !item.text) continue;
    const start = text.indexOf(item.text);
    if (start < 0) continue;
    ranges.push({ start, end: start + item.text.length, item });
  }
  ranges.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));
  const picked = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue;
    picked.push(range);
    cursor = range.end;
  }
  const parts = [];
  let index = 0;
  for (const range of picked) {
    if (range.start > index) {
      parts.push({ type: 'plain', text: text.slice(index, range.start) });
    }
    parts.push({
      type: 'mark',
      text: text.slice(range.start, range.end),
      item: range.item,
    });
    index = range.end;
  }
  if (index < text.length) parts.push({ type: 'plain', text: text.slice(index) });
  return parts;
}

function parseSSEChunk(raw) {
  let event = 'message';
  const dataLines = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  return { event, data: JSON.parse(dataLines.join('\n')) };
}

/** 二交代。8:00–17:00 を日勤、それ以外を夜勤の初期値にする。 */
function defaultShift() {
  const h = new Date().getHours();
  return h >= 8 && h < 17 ? '日勤' : '夜勤';
}

function todayStr() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return d.getFullYear() + '-' + m + '-' + day;
}

function emptyAdmitState() {
  return {
    open: false,
    keyword: '',
    results: [],
    searched: false,
    newPatientMode: false,
    newPatient: { karte_no: '', name: '', name_kana: '', birth_date: '', sex: '男性' },
    patient: null,
    form: { admitted_at: todayStr(), room: '', diagnosis: '', attending_doctor: '' },
    busy: false,
    error: '',
  };
}

Vue.createApp({
  data() {
    return {
      // --- 認証 ---
      loggedIn: false,
      me: {},
      loginForm: { employee_no: '', password: '' },
      loginError: '',
      loading: false,

      // --- 患者 ---
      keyword: '',
      patients: [],
      selectedId: null,
      patient: null,

      // --- 看護記録 ---
      tab: 'note',
      days: 7,
      notes: [],
      generating: false,
      genStatus: '',
      generated: '',
      contentAi: '',
      evidence: [],
      genMeta: emptyGenMeta(),
      derivedText: '',
      saving: false,
      saveMessage: '',
      checkItems: [
        '食事全量', '食事半量', '排便あり', '疼痛訴えあり',
        '歩行器で移動', '車椅子移動', '不眠', '発熱あり', '創部処置',
      ],
      today: {
        bt: '', bp: '', hr: '', spo2: '', rr: '',
        checks: [],
        free: '',
        shift: defaultShift(),
        format: 'SOAP',
      },

      // --- 新規入院モーダル ---
      admit: emptyAdmitState(),
    };
  },

  computed: {
    /** 現在（または直近）の入院情報。未入院なら null */
    adm() {
      return this.patient ? this.patient.current_admission : null;
    },
    hasAllergy() {
      return this.patient
        && this.patient.assessment
        && this.patient.assessment.allergies
        && this.patient.assessment.allergies.length > 0;
    },
    hospitalDays() {
      if (!this.adm) return '';
      const start = new Date(this.adm.admitted_at);
      const diff = Math.floor((new Date() - start) / 86400000);
      return diff + 1;
    },
    adlText() {
      const adl = this.patient && this.patient.assessment && this.patient.assessment.adl;
      if (!adl) return '－';
      return Object.keys(adl).map((k) => k + '：' + adl[k]).join('　/　');
    },
    previewParts() {
      return buildPreview(this.generated, this.evidence);
    },
  },

  methods: {
    // ----------------------------------------------------------- 認証
    async login() {
      this.loginError = '';
      this.loading = true;
      try {
        const res = await api('POST', '/auth/login', {
          body: {
            employee_no: this.loginForm.employee_no,
            password: this.loginForm.password,
          },
        });
        localStorage.setItem(TOKEN_KEY, res.access_token);
        this.me = res.nurse;
        this.loggedIn = true;
        await this.searchPatients();
      } catch (e) {
        this.loginError = e.detail || 'ログインに失敗しました';
      } finally {
        this.loading = false;
      }
    },

    logout() {
      localStorage.removeItem(TOKEN_KEY);
      this.loggedIn = false;
      this.me = {};
      this.patients = [];
      this.patient = null;
      this.selectedId = null;
      this.loginForm.password = '';
    },

    async restoreSession() {
      if (!localStorage.getItem(TOKEN_KEY)) return;
      try {
        this.me = await api('GET', '/auth/me');
        this.loggedIn = true;
        await this.searchPatients();
      } catch (e) {
        // 期限切れトークンは捨ててログイン画面に戻す
        localStorage.removeItem(TOKEN_KEY);
      }
    },

    // ----------------------------------------------------------- 担当患者一覧
    /** 入院中の担当患者だけを取得する（scope は既定の admitted） */
    async searchPatients() {
      try {
        const res = await api('GET', '/patients', { params: { q: this.keyword } });
        this.patients = res;
        // 選択中の患者が一覧から消えたら先頭を選び直す
        if (!res.some((p) => p.id === this.selectedId)) {
          if (res.length > 0) {
            await this.selectPatient(res[0].id);
          } else {
            this.selectedId = null;
            this.patient = null;
            this.notes = [];
          }
        }
      } catch (e) {
        if (e.status === 401) this.logout();
        else alert(e.detail || '患者の検索に失敗しました');
      }
    },

    async selectPatient(id) {
      this.selectedId = id;
      this.discardDraft();
      this.today.checks = [];
      this.today.free = '';
      try {
        this.patient = await api('GET', '/patients/' + id);
        await this.loadNotes();
      } catch (e) {
        alert(e.detail || '患者情報の取得に失敗しました');
      }
    },

    // ----------------------------------------------------------- 看護記録
    async loadNotes() {
      if (!this.selectedId) return;
      try {
        const res = await api('GET', '/patients/' + this.selectedId + '/notes', {
          params: { days: this.days },
        });
        this.notes = res.items;
      } catch (e) {
        alert(e.detail || '看護記録の取得に失敗しました');
      }
    },

    todayPayload() {
      return {
        patient_id: this.selectedId,
        shift: this.today.shift,
        format: this.today.format,
        vitals: {
          bt: this.today.bt, bp: this.today.bp, hr: this.today.hr,
          spo2: this.today.spo2, rr: this.today.rr,
        },
        checks: this.today.checks,
        free_text: this.today.free,
      };
    },

    async generate() {
      this.generating = true;
      this.genStatus = '準備しています…';
      this.saveMessage = '';
      this.derivedText = '';
      this.generated = '';
      this.contentAi = '';
      this.evidence = [];
      this.genMeta = emptyGenMeta();
      try {
        const headers = { 'Content-Type': 'application/json' };
        const token = localStorage.getItem(TOKEN_KEY);
        if (token) headers.Authorization = 'Bearer ' + token;
        const res = await fetch('/api/v1/notes/generate', {
          method: 'POST',
          headers,
          body: JSON.stringify(this.todayPayload()),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new ApiError(res.status, extractDetail(data) || '生成に失敗しました');
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let donePayload = null;
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          let splitAt;
          while ((splitAt = buffer.indexOf('\n\n')) >= 0) {
            const raw = buffer.slice(0, splitAt);
            buffer = buffer.slice(splitAt + 2);
            const parsed = parseSSEChunk(raw);
            if (!parsed) continue;
            if (parsed.event === 'status') {
              this.genStatus = parsed.data.phase === 'retrieve'
                ? '過去の記録を参照しています…'
                : '記録を生成しています…';
            } else if (parsed.event === 'delta') {
              this.generated += parsed.data.text || '';
            } else if (parsed.event === 'error') {
              throw new ApiError(0, parsed.data.detail || '生成に失敗しました');
            } else if (parsed.event === 'done') {
              donePayload = parsed.data;
            }
          }
        }
        if (!donePayload) throw new ApiError(0, '生成が完了しませんでした');
        this.generated = donePayload.content || this.generated;
        this.contentAi = donePayload.content || '';
        this.evidence = donePayload.evidence || [];
        this.genMeta = {
          model_name: donePayload.model_name || null,
          prompt_version: donePayload.prompt_version || null,
          token_usage: donePayload.token_usage || null,
        };
      } catch (e) {
        alert(e.detail || e.message || '生成に失敗しました');
      } finally {
        this.generating = false;
        this.genStatus = '';
      }
    },

    async confirmNote() {
      if (!this.generated.trim()) return;
      this.saving = true;
      this.saveMessage = '';
      try {
        await api('POST', '/notes', {
          body: {
            ...this.todayPayload(),
            content_ai: this.contentAi,
            content_final: this.generated,
            evidence: this.evidence,
            model_name: this.genMeta.model_name,
            prompt_version: this.genMeta.prompt_version,
            token_usage: this.genMeta.token_usage,
          },
        });
        this.discardDraft();
        this.saveMessage = '確定して保存しました';
        await this.loadNotes();
      } catch (e) {
        alert(e.detail || '保存に失敗しました');
      } finally {
        this.saving = false;
      }
    },

    discardDraft() {
      this.generated = '';
      this.contentAi = '';
      this.evidence = [];
      this.genMeta = emptyGenMeta();
      this.derivedText = '';
      this.saveMessage = '';
    },

    evidenceClass(item) {
      if (!item) return '';
      if (item.source_type === 'clinical_inference') return 'ev-infer';
      if (item.source_type === 'historical_note' || item.source_type === 'patient_profile') {
        return 'ev-hist';
      }
      return '';
    },

    showDerived(item) {
      if (!item || item.source_type !== 'clinical_inference') {
        this.derivedText = '';
        return;
      }
      const refs = (item.derived_from || []).join('、');
      this.derivedText = refs ? 'この解釈の根拠: ' + refs : '根拠の参照がありません';
    },

    // ----------------------------------------------------------- 新規入院
    openAdmit() {
      this.admit = emptyAdmitState();
      this.admit.open = true;
    },

    closeAdmit() {
      this.admit.open = false;
    },

    /** 患者マスタ全体から検索する（未入院・退院済も対象） */
    async searchMaster() {
      const kw = (this.admit.keyword || '').trim();
      if (!kw) {
        this.admit.error = '検索語を入力してください';
        return;
      }
      this.admit.error = '';
      try {
        this.admit.results = await api('GET', '/patients', {
          params: { q: kw, scope: 'all' },
        });
        this.admit.searched = true;
      } catch (e) {
        this.admit.error = e.detail || '患者マスタの検索に失敗しました';
      }
    },

    async createPatient() {
      const np = this.admit.newPatient;
      if (!np.name.trim()) {
        this.admit.error = '氏名を入力してください';
        return;
      }
      this.admit.error = '';
      this.admit.busy = true;
      try {
        this.admit.patient = await api('POST', '/patients', {
          body: {
            karte_no: (np.karte_no || '').trim() || null,
            name: np.name,
            name_kana: np.name_kana || null,
            birth_date: np.birth_date || null,
            sex: np.sex || null,
          },
        });
        this.admit.newPatientMode = false;
      } catch (e) {
        this.admit.error = e.detail || '患者の登録に失敗しました';
      } finally {
        this.admit.busy = false;
      }
    },

    async submitAdmission() {
      if (!this.admit.patient) return;
      this.admit.error = '';
      this.admit.busy = true;
      const f = this.admit.form;
      try {
        await api('POST', '/admissions', {
          body: {
            patient_id: this.admit.patient.id,
            admitted_at: f.admitted_at || null,
            room: f.room || null,
            diagnosis: f.diagnosis || null,
            attending_doctor: f.attending_doctor || null,
          },
        });
        const newId = this.admit.patient.id;
        this.admit.open = false;
        this.keyword = '';
        // 一覧を取り直してから、登録した患者を選択する
        this.patients = await api('GET', '/patients');
        await this.selectPatient(newId);
      } catch (e) {
        this.admit.error = e.detail || '入院登録に失敗しました';
      } finally {
        this.admit.busy = false;
      }
    },

    async discharge() {
      if (!this.adm) return;
      if (!confirm(this.patient.name + ' さんの退院処理を行います。よろしいですか？')) {
        return;
      }
      try {
        await api('POST', '/admissions/' + this.adm.id + '/discharge', { body: {} });
        const id = this.selectedId;
        // searchPatients() の自動選択と競合しないよう、ここでは直接取得する
        this.patients = await api('GET', '/patients');
        // 退院した患者の情報は引き続き参照できるようにしておく
        await this.selectPatient(id);
      } catch (e) {
        alert(e.detail || '退院処理に失敗しました');
      }
    },

    // ----------------------------------------------------------- 表示補助
    statusLabel(s) {
      return s === 'confirmed' ? '確定済' : '下書き';
    },
    /** 生年月日が未登録なら年齢は空になるので、その場合の表示を用意する */
    ageText(age) {
      return age === null || age === undefined ? '年齢不明' : age + '歳';
    },
    admissionLabel(s) {
      if (s === 'admitted') return '入院中';
      if (s === 'discharged') return '退院済';
      return '入院歴なし';
    },
    joinOr(arr, fallback) {
      return arr && arr.length ? arr.join('、') : fallback;
    },
  },

  mounted() {
    this.restoreSession();
  },
}).mount('#app');
