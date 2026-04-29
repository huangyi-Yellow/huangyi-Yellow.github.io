"""
法律类案分析系统 — Streamlit（本地规则引擎 + 类 ChatGPT 交互界面）
支持多 PDF、案件简要、语音输入（需联网调用 Google 语音识别）
启动: streamlit run app.py
"""

from __future__ import annotations

import io
import re
from io import BytesIO

import streamlit as st
from pypdf import PdfReader

try:
    from audio_recorder_streamlit import audio_recorder
except ImportError:
    audio_recorder = None  # type: ignore[misc, assignment]

try:
    import speech_recognition as sr
except ImportError:
    sr = None  # type: ignore[misc, assignment]

# --- 关键词模板（互联网法务视角）---
PROFILES: dict[str, dict[str, list[str]]] = {
    "平台": {
        "issues": [
            "平台作为网络服务提供者或电子商务平台经营者，其身份认定及是否适用“通知—必要措施”规则、安全保障义务或连带责任条款。",
            "平台对入驻经营者资质核验、信息公示、交易记录保存及协助取证义务是否履行到位，是否影响责任范围。",
            "平台是否从交易中获得直接经济利益，进而影响过错认定与责任比例。",
        ],
        "rules": [
            "结合《电子商务法》《民法典》侵权责任编及司法解释，审查平台过错、明知或应知、是否采取必要措施等裁判要素。",
            "参考“红旗标准”等规则判断平台对明显侵权或违法信息的注意义务边界。",
            "在消费者权益争议中，依法审查信息披露、先行赔付承诺与格式条款效力。",
        ],
        "risks": [
            "可操作建议：完善入驻协议与平台规则版本管理，明确违规处置流程与证据留存（日志、操作记录、通知送达凭证）。",
            "可操作建议：建立标准化侵权/投诉受理与反馈时限，对重复投诉与恶意投诉设置甄别机制并留痕。",
            "可操作建议：对高风险类目建立巡查清单与抽检比例，重大风险事件启动法务、公关、客服联合响应。",
        ],
    },
    "消费者": {
        "issues": [
            "消费者身份是否成立，争议是否属于生活消费；惩罚性赔偿（欺诈）或七日无理由退货等主张的事实与法律依据是否充分。",
            "举证责任是否因耐用商品等情形发生倒置，经营者是否承担瑕疵举证义务。",
            "是否存在群体性纠纷或舆论风险，对平台商誉与监管约谈的溢出影响。",
        ],
        "rules": [
            "依《消费者权益保护法》及相关司法解释，审查虚假宣传、欺诈认定标准及退一赔三等适用条件。",
            "电子商务场景下信息披露、格式条款提示说明义务与显著标识要求的审查要点。",
            "结合《电子商务法》对平台内经营者标识、信用评价、争议解决机制的要求进行认定。",
        ],
        "risks": [
            "可操作建议：在订单页、活动页对关键条款进行显著提示并留存用户勾选/确认记录，避免“默认勾选”合规风险。",
            "可操作建议：建立售后工单分类与升级机制，对群体性投诉启动法务与公关协同预案。",
            "可操作建议：对促销规则设置冲突校验（价格、库存、赠品），防范虚假优惠与宣传不一致。",
        ],
    },
    "个人信息": {
        "issues": [
            "个人信息处理合法性基础（同意、合同必要、法定义务等）是否充分，敏感个人信息是否单独同意。",
            "跨境提供、委托处理、共享第三方时的告知同意与数据出境安全评估义务是否触发。",
            "自动化决策、个性化推荐是否保障用户拒绝权与说明义务。",
        ],
        "rules": [
            "依《个人信息保护法》审查最小必要、目的限制、公开透明原则及个人信息主体权利的响应机制。",
            "监管与司法中对“单独同意”“重新取得同意”及匿名化、去标识化边界的认定思路。",
            "共同处理、委托处理、对外提供三类场景下的合同与记录义务区分。",
        ],
        "risks": [
            "可操作建议：更新隐私政策与产品内弹窗流程，区分基础功能与扩展功能授权，保存同意时间戳与版本号。",
            "可操作建议：对第三方SDK开展合规尽调与合同约束，建立数据处理记录（RoPA）与定期审计。",
            "可操作建议：建立数据泄露应急预案与对内演练，明确对外通报与客户告知口径。",
        ],
    },
    "广告": {
        "issues": [
            "商业宣传是否构成虚假或引人误解的宣传，是否涉及绝对化用语或需取得行政许可而未取得的情形。",
            "直播带货、种草推广中广告主、广告经营者、发布者及平台责任如何切割。",
            "对比广告、引用数据是否可验证，是否侵犯竞争对手合法权益。",
        ],
        "rules": [
            "依《广告法》《反不正当竞争法》审查真实性、比对广告、代言责任及平台审核义务。",
            "互联网广告可识别性、显著标明“广告”及跳转落地页一致性等合规要求。",
            "对医疗、药品、保健食品等特别行业广告审查标准的适用。",
        ],
        "risks": [
            "可操作建议：建立营销物料法务审核清单（功效数据、对比实验、免责提示），对KOL合作明确内容合规与连带责任条款。",
            "可操作建议：对算法推荐与定向投放建立敏感行业黑名单与人工抽检机制。",
            "可操作建议：直播脚本与口播禁区清单前置评审，关键承诺落书面确认。",
        ],
    },
    "直播": {
        "issues": [
            "直播间运营主体、MCN、主播之间的法律关系及对外承担责任的主体认定。",
            "商品缺陷、虚假宣传或售后服务争议中，平台是否承担连带责任或补充责任。",
            "未成年人保护、违禁品与价格欺诈在直播场景下的合规边界。",
        ],
        "rules": [
            "结合《网络直播营销管理办法（试行）》等规范，审查信息披露、样品核对、投诉处理等义务。",
            "消费者权益保护视角下，直播场景举证与先行赔付、平台内经营者标识义务。",
            "对直播回放、弹幕、链接跳转等证据形式的可采性与证明力评估。",
        ],
        "risks": [
            "可操作建议：在直播协议中明确选品标准、样品留存、话术禁区与违规处罚，并对高风险品类提高保证金或保险要求。",
            "可操作建议：对主播进行定期合规培训并考试留档，建立实时巡查与关键词预警。",
            "可操作建议：建立先行赔付与追偿机制模板，降低消费者维权成本与舆情外溢。",
        ],
    },
    "内容": {
        "issues": [
            "用户生成内容（UGC）侵权或违法情形下，平台是否尽到合理注意义务及是否及时采取必要措施。",
            "名誉权、著作权、人格权纠纷中，平台提供网络服务与直接侵权的界限。",
            "算法推荐、热榜运营是否构成“应知”或提高注意义务的事实情节。",
        ],
        "rules": [
            "依“通知—删除”规则及必要措施标准，结合案件事实判断平台过错与责任范围。",
            "重复侵权、热门榜单、编辑推荐等是否提高平台注意义务水平的裁判考量。",
            "对有效通知的形式要件与反通知程序的衔接审查。",
        ],
        "risks": [
            "可操作建议：优化侵权投诉入口与反通知流程，设定合理处理时限并保存全流程文书。",
            "可操作建议：对高热内容与账号建立分级管控与人工复核策略，防范“应知”风险。",
            "可操作建议：建立版权合作与白名单机制，降低反复投诉对业务的冲击。",
        ],
    },
    "合同": {
        "issues": [
            "网络服务协议、用户协议、平台规则等格式条款的效力与解释，是否存在免除己方责任、加重对方责任等无效情形。",
            "电子合同订立、身份认证、存证与争议解决条款（含仲裁、管辖）是否有效。",
            "平台单方变更规则与对存量用户、存量订单的约束力与提示义务。",
        ],
        "rules": [
            "依《民法典》合同编及司法解释审查格式条款提示说明义务与公平原则。",
            "电子商务合同成立、标的交付、风险转移及违约救济的认定规则。",
            "电子签名法框架下可靠电子签名与数据电文证据效力。",
        ],
        "risks": [
            "可操作建议：对免责与限制责任条款采用加粗、分步确认，并保留用户已阅读的交互证据。",
            "可操作建议：重大规则变更前履行公示与异议处理程序，评估对存量订单的影响。",
            "可操作建议：建立合同版本库与争议发生时快速调取机制。",
        ],
    },
    "劳动": {
        "issues": [
            "用工关系是否被认定为劳动关系或劳务派遣、外包混同，互联网平台用工形态下的责任主体。",
            "竞业限制、保密义务、知识产权归属与员工违纪解除的合规性与证据充分性。",
            "远程办公、账号权限与数据安全在劳动争议中的交叉问题。",
        ],
        "rules": [
            "依《劳动合同法》等审查从属性、报酬支付、管理指挥等要素。",
            "劳动争议仲裁前置、举证责任分配及规章制度民主程序与公示要求。",
            "对股权激励、虚拟资产归属等新型争议的处理思路。",
        ],
        "risks": [
            "可操作建议：厘清业务外包与假外包真用工，统一合同、结算与现场管理口径，避免混同指挥。",
            "可操作建议：完善员工行为守则与信息安全培训，离职交接与账号权限回收流程制度化。",
            "可操作建议：对核心研发与涉密岗位强化留痕与设备管理，降低商业秘密泄露风险。",
        ],
    },
}

DEFAULT_ISSUES = [
    "本案核心法律关系是否涉及网络服务、电子商务或数字产品服务，平台/经营者在交易结构中的角色与义务边界如何界定。",
    "争议是否围绕信息披露、公平交易、安全保障或个人信息处理等消费者权益与平台责任交叉领域展开。",
    "在事实不清情形下，举证责任分配、证据形式（电子数据、日志、第三方存证）及证明标准是否构成关键争点。",
    "是否涉及监管执法、行业自律规则或平台自治规则（社区公约、处罚规则）的适用与冲突。",
    "是否存在跨法域、跨境数据或涉外主体带来的法律适用与执行难题。",
]

DEFAULT_RULES = [
    "裁判通常综合《民法典》《消费者权益保护法》《电子商务法》《个人信息保护法》等，结合行业监管规则与诚实信用原则认定责任。",
    "涉及平台责任时，司法机关多从过错、明知或应知、是否采取必要措施、是否直接获利等维度进行说理与裁量。",
    "消费者权益案件中，对经营者优势地位、信息不对称及格式条款提示义务给予适度倾斜保护，但仍以事实与证据为基础。",
    "对电子证据的真实性、完整性审查常结合时间戳、哈希、第三方存证与平台后台记录相互印证。",
    "类案检索与指导性案例的说理价值上升，但具体案件仍以事实认定与要件审查为核心。",
]

DEFAULT_RISKS = [
    "可操作建议：由法务牵头建立跨部门（产品、运营、客服、安全）案件复盘机制，将个案风险转化为规则更新与培训主题。",
    "可操作建议：对涉诉业务线同步启动证据保全（服务器日志、合同版本、沟通记录），并评估对外披露与舆情应对口径。",
    "可操作建议：在类似业务场景前置合规评审（上线前 checklist），对高风险功能配置人工审核与熔断策略。",
    "可操作建议：建立对外声明与媒体应答模板，避免员工个人言论被认定为职务行为或表见代理风险。",
    "可操作建议：与外部律师协同制定调解、和解与诉讼策略矩阵，控制时间与费用成本。",
]

NEXT_STEPS_HINTS = [
    "可补充：平台规则具体条款版本、用户协议勾选与变更记录、投诉工单与处理日志。",
    "可补充：涉案商品/服务的上架审核材料、广告素材审批单、直播脚本与样品核对记录。",
    "可补充：与监管部门的沟通函件、整改报告及是否涉及行政处罚或约谈。",
]


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("PDF 已加密，请先解密后再上传。") from None
    texts: list[str] = []
    for page in reader.pages:
        texts.append(page.extract_text() or "")
    return "\n".join(texts).strip()


def _ensure_n_simple(primary: list[str], fallback: list[str], n: int) -> list[str]:
    merged = _dedupe(primary + fallback)
    if len(merged) >= n:
        return merged[:n]
    for line in fallback:
        if len(merged) >= n:
            break
        if line not in merged:
            merged.append(line)
    return merged[:n]


def build_case_digest(combined: str, pdf_names: list[str], max_chars: int = 420) -> str:
    """案情与材料综述（截取 + 结构化说明）。"""
    t = combined.strip()
    if not t:
        return "（未提供可分析文本）"
    excerpt = t[:max_chars].strip()
    if len(t) > max_chars:
        excerpt += "……"
    pdf_line = "、".join(pdf_names) if pdf_names else "（未上传 PDF 或未能提取文件名）"
    han = len(re.findall(r"[\u4e00-\u9fff]", t))
    return (
        f"- **材料来源**：PDF 文件 {pdf_line}\n"
        f"- **文本规模**：约 {han} 个汉字等效字符（粗略统计，供评估信息充分性参考）\n"
        f"- **内容摘录**：{excerpt}"
    )


def analyze_detailed(case_text: str, pdf_names: list[str]) -> str:
    """详细分析：综述 + 三节各 5 条 + 后续核证建议。"""
    t = case_text.strip()
    if not t:
        return ""

    issues: list[str] = []
    rules: list[str] = []
    risks: list[str] = []

    for kw, block in PROFILES.items():
        if kw in t:
            issues.extend(block["issues"])
            rules.extend(block["rules"])
            risks.extend(block["risks"])

    if not issues:
        issues = list(DEFAULT_ISSUES)
        rules = list(DEFAULT_RULES)
        risks = list(DEFAULT_RISKS)
    else:
        issues = _dedupe(issues)
        rules = _dedupe(rules)
        risks = _dedupe(risks)

    n = 5
    fi = _ensure_n_simple(issues, DEFAULT_ISSUES, n)
    fr = _ensure_n_simple(rules, DEFAULT_RULES, n)
    fk = _ensure_n_simple(risks, DEFAULT_RISKS, n)

    wordish = len(re.findall(r"[\u4e00-\u9fff]", t))
    short_hint = ""
    if wordish < 80:
        short_hint = (
            "\n> **提示**：材料篇幅偏短，下列分析以框架性与可复核问题为主；建议补充订单、日志、规则版本与沟通记录后再迭代。\n\n"
        )

    digest = build_case_digest(t, pdf_names)

    def numbered_block(title: str, lines: list[str]) -> str:
        body = "\n".join(f"{i + 1}. {lines[i]}" for i in range(min(n, len(lines))))
        return f"{title}\n{body}"

    follow = "\n".join(f"- {x}" for x in NEXT_STEPS_HINTS[:3])

    return (
        f"{short_hint}"
        f"### 一、案情与材料综述\n{digest}\n\n"
        f"### 二、详细分析\n\n"
        f"{numbered_block('【争议焦点】', fi)}\n\n"
        f"{numbered_block('【裁判规则】', fr)}\n\n"
        f"{numbered_block('【法律风险提示】', fk)}\n\n"
        f"### 三、建议进一步核证与互动方向\n{follow}\n"
    )


def followup_reply(full_context: str, question: str) -> str:
    """本地互动：基于关键词的简要追问回应（非大模型）。"""
    q = question.strip()
    if not q:
        return "请输入有效问题。"

    hits: list[str] = []
    for kw, block in PROFILES.items():
        if kw in q or kw in full_context[:2000]:
            hits.append(kw)

    lines: list[str] = [
        "以下为基于您已提供材料与追问要点的**辅助性梳理**，仍不构成法律意见。",
        "",
    ]

    if "平台" in q or "责任" in q:
        lines.append(
            "**平台责任侧**：建议重点梳理您是否在收到有效通知后及时采取必要措施、是否对明显违法信息存在应知情形，以及是否从涉案交易中直接获得经济利益；同步准备后台日志、处理工单与规则版本。"
        )
    if "消费者" in q or "退款" in q or "赔偿" in q:
        lines.append(
            "**消费者权益侧**：核对是否属于生活消费、是否存在欺诈或虚假宣传主张，证据上准备订单、宣传页面快照、沟通记录与鉴定/检测报告（如适用）。"
        )
    if "个人信息" in q or "数据" in q or "隐私" in q:
        lines.append(
            "**个人信息与数据合规**：梳理处理目的、合法性基础、告知同意文本与第三方共享清单，评估是否需要个人信息保护影响评估或出境场景补充材料。"
        )
    if "证据" in q or "举证" in q:
        lines.append(
            "**证据与程序**：建议制作证据清单（电子数据哈希、时间戳、公证或平台出具证明），并关注管辖、仲裁条款与诉讼时效/除斥期间。"
        )

    if len(lines) <= 2:
        lines.append(
            "您可以继续说明：争议主体（平台/商家/用户）、主要诉求、已采取的投诉或诉讼步骤，以及希望我侧重**平台义务**、**消费者保护**还是**内部合规整改**中的哪一条线，以便收窄分析范围。"
        )

    lines.append("")
    lines.append("如需重新上传更完整材料，可使用侧栏 **新对话** 清空会话后再提交。")
    return "\n\n".join(lines)


def inject_styles() -> None:
    st.markdown(
        """
<style>
  /* 整体：偏 ChatGPT 的清爽浅色底 */
  .stApp {
    background: linear-gradient(180deg, #f6f7fb 0%, #eef1f8 100%);
  }
  [data-testid="stHeader"] { background: rgba(255,255,255,0); }
  [data-testid="stToolbar"] { visibility: hidden; height: 0; position: fixed; top: -9999px; }
  section[data-testid="stSidebar"] > div {
    background: linear-gradient(180deg, #111827 0%, #1f2937 100%) !important;
    color: #e5e7eb;
  }
  section[data-testid="stSidebar"] .stMarkdown { color: #e5e7eb; }
  section[data-testid="stSidebar"] small { color: #9ca3af !important; }
  .composer-card {
    border: 1px solid #e5e7eb;
    border-radius: 16px;
    padding: 1rem 1.25rem 1.25rem 1.25rem;
    background: #ffffffcc;
    backdrop-filter: blur(8px);
    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
    margin-bottom: 1rem;
  }
  .hero-title {
    font-size: 1.65rem;
    font-weight: 650;
    letter-spacing: -0.02em;
    color: #111827;
    margin-bottom: 0.25rem;
  }
  .hero-sub {
    color: #6b7280;
    font-size: 0.95rem;
    margin-bottom: 1rem;
  }
  div[data-testid="stChatMessage"] { background: #ffffffaa; border-radius: 14px; border: 1px solid #eef2f7; }
</style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "context_blob" not in st.session_state:
        st.session_state.context_blob = ""
    if "file_uploader_key" not in st.session_state:
        st.session_state.file_uploader_key = 0
    if "voice_note" not in st.session_state:
        st.session_state.voice_note = ""


def main() -> None:
    st.set_page_config(
        page_title="法律类案分析",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_state()
    inject_styles()

    with st.sidebar:
        st.markdown("### 法律类案分析")
        st.caption("企业合规视角 · 本地规则引擎")
        if st.button("新对话", use_container_width=True, type="primary"):
            st.session_state.messages = []
            st.session_state.context_blob = ""
            st.session_state.voice_note = ""
            st.session_state.file_uploader_key += 1
            st.rerun()
        st.divider()
        st.caption(
            "说明：本工具为辅助梳理，不构成法律意见。语音转写使用浏览器录音后由服务端识别（默认需联网）。"
        )

    left, center, right = st.columns([0.15, 0.7, 0.15])
    with center:
        st.markdown('<p class="hero-title">法律类案分析</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="hero-sub">上传多份 PDF、填写简要，或使用语音补充说明；生成后可继续对话追问。</p>',
            unsafe_allow_html=True,
        )

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        with st.expander("上传材料与填写说明", expanded=True):
            st.caption("支持多份 PDF 自动抽取文字 + 简要 + 语音补充")

            uploads = st.file_uploader(
                "上传 PDF（可多选，建议≤10 份）",
                type=["pdf"],
                accept_multiple_files=True,
                key=f"pdfs_{st.session_state.file_uploader_key}",
                help="自动抽取可复制文字；扫描件可能无法识别",
            )

            brief = st.text_area(
                "案件简要",
                height=160,
                placeholder="用一段话概括：主体、时间线、诉求、已知程序与争议点……",
                label_visibility="collapsed",
            )
            st.caption("案件简要")

            st.markdown("**语音输入**（点击录音，停止后自动识别）")
            if audio_recorder is not None and sr is not None:
                audio_bytes = audio_recorder(
                    text="点击录音",
                    pause_threshold=2.5,
                    recording_color="#ef4444",
                    neutral_color="#6b7280",
                )
                if audio_bytes:
                    try:
                        r = sr.Recognizer()
                        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
                            audio = r.record(source)
                        try:
                            transcribed = r.recognize_google(audio, language="zh-CN")
                            st.session_state.voice_note = transcribed
                            st.success("语音识别完成，已更新到会话（见下方预览）。")
                        except sr.UnknownValueError:
                            st.warning("未能识别语音内容，请靠近麦克风、减少背景噪音后重试。")
                        except sr.RequestError as e:
                            st.error(f"语音识别服务不可用（需联网）：{e}")
                    except Exception as e:
                        st.error(f"处理录音失败：{e}")
            else:
                st.info(
                    "未安装语音组件。请执行：`pip install audio-recorder-streamlit SpeechRecognition` 后重启。"
                )

            if st.session_state.voice_note:
                st.caption("语音识别预览")
                st.code(st.session_state.voice_note, language=None)

            col_a, col_b = st.columns(2)
            with col_a:
                merge_voice = st.checkbox("将语音转写合并进本次分析", value=True)
            with col_b:
                if st.button("清空语音转写"):
                    st.session_state.voice_note = ""
                    st.rerun()

            run = st.button("生成详细分析", type="primary", use_container_width=True)

        if run:
            parts: list[str] = []
            pdf_names: list[str] = []
            if uploads:
                for f in uploads:
                    pdf_names.append(getattr(f, "name", "未命名.pdf"))
                    try:
                        raw = f.getvalue()
                        pdf_text = extract_text_from_pdf(raw)
                        if pdf_text:
                            parts.append(f"### PDF：{f.name}\n{pdf_text}")
                        else:
                            st.warning(f"《{f.name}》未识别到文字，可能是扫描件。")
                    except Exception as e:
                        st.error(f"读取 {f.name} 失败：{e}")

            if brief.strip():
                parts.append(f"### 案件简要\n{brief.strip()}")

            vtxt = st.session_state.voice_note.strip() if merge_voice else ""
            if vtxt:
                parts.append(f"### 语音整理\n{vtxt}")

            combined = "\n\n---\n\n".join(parts).strip()

            if not combined:
                st.warning("请至少上传可识别的 PDF、填写案件简要，或先完成语音输入。")
            else:
                st.session_state.context_blob = combined
                with st.spinner("正在阅读材料并生成详细分析……"):
                    analysis = analyze_detailed(combined, pdf_names)

                user_face = []
                if pdf_names:
                    user_face.append(f"- PDF：共 {len(pdf_names)} 份（{ '、'.join(pdf_names[:5])}{'…' if len(pdf_names) > 5 else ''}）")
                if brief.strip():
                    user_face.append(f"- 简要：{brief.strip()[:400]}{'…' if len(brief.strip()) > 400 else ''}")
                if merge_voice and st.session_state.voice_note.strip():
                    user_face.append(f"- 语音整理：{st.session_state.voice_note.strip()[:300]}{'…' if len(st.session_state.voice_note.strip()) > 300 else ''}")

                user_msg = "**本轮材料已提交**\n" + (
                    "\n".join(user_face) if user_face else combined[:1200]
                )
                pair = [
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": analysis},
                ]
                if st.session_state.messages:
                    st.session_state.messages.extend(pair)
                else:
                    st.session_state.messages = pair
                st.rerun()

        has_thread = bool(st.session_state.messages)
        follow = st.chat_input(
            "继续提问（例如：平台责任如何抗辩？需要补充哪些证据？）"
            if has_thread
            else "请先在上方提交材料并点击「生成详细分析」",
            disabled=not has_thread,
            key="followup_input",
        )
        if follow and has_thread:
            ans = followup_reply(st.session_state.context_blob, follow)
            st.session_state.messages.append({"role": "user", "content": follow})
            st.session_state.messages.append({"role": "assistant", "content": ans})
            st.rerun()

    st.caption("")


