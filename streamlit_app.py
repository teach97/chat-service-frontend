"""20일차 완성본 — 실시간 응답과 피드백 UX.

오늘은 사용자의 행동과 시스템의 상태를 1대1로 잇는다.

    사용자가 겪는 것        화면이 하는 일
    --------------------   --------------------------------
    답이 늦다               글자가 나오는 대로 흘려보낸다
    답을 못 받았다           같은 질문으로 `다시 시도`
    답이 마음에 안 든다       기존 답을 지우고 `다시 생성`
    답이 좋았다/아쉬웠다      `도움됨` / `아쉬움` 을 남긴다

`다시 시도`와 `다시 생성`은 다르다. 하나는 실패를 복구하는 것이고,
다른 하나는 성공한 결과를 바꾸는 것이다.
"""

import streamlit as st

from common import (
    ApiError,
    SERVICE_NAME,
    SessionExpired,
    api,
    auth_headers,
    conversation_label,
    stream_answer,
)

st.set_page_config(page_title=SERVICE_NAME, layout="centered")

st.session_state.setdefault("access_token", None)
st.session_state.setdefault("user_email", None)
st.session_state.setdefault("conversation_id", None)
st.session_state.setdefault("pending_question", None)
# 세션이 풀린 이유를 다음 실행에서 보여주려고 남겨둔다.
# 토큰만 지우고 끝내면 사용자는 자기가 왜 로그아웃됐는지 모른다.
st.session_state.setdefault("expired_notice", None)
# 답을 못 받은 질문. `다시 시도` 버튼이 이것을 쓴다.
st.session_state.setdefault("failed_question", None)

EXAMPLE_QUESTIONS = [
    "면접을 시작해 주세요.",
    "1분 자기소개를 해보겠습니다.",
    "제 이력서에서 가장 많이 받을 질문이 뭘까요?",
]


def sign_out(notice: str | None = None) -> None:
    """로그인 관련 상태를 한 번에 지운다.

    지울 것을 빠뜨리면 다음 사용자에게 앞사람의 대화가 잠깐 보인다.
    그래서 로그아웃과 세션 만료가 같은 함수를 쓰게 해둔다.
    """
    st.session_state.access_token = None
    st.session_state.user_email = None
    st.session_state.conversation_id = None
    st.session_state.pending_question = None
    st.session_state.failed_question = None
    st.session_state.expired_notice = notice
    st.rerun()


@st.cache_data(ttl=300)
def load_options() -> dict:
    return api("GET", "/chat/options")


def render_login() -> None:
    """비로그인 상태의 화면 전체."""
    if st.session_state.expired_notice:
        st.warning(st.session_state.expired_notice)

    st.write("직무를 정하고 면접 질문에 답하며 연습합니다. 기록은 계정에 저장됩니다.")

    email = st.text_input("이메일", placeholder="you@example.com")
    password = st.text_input("비밀번호", type="password")

    login_column, signup_column = st.columns(2)
    action = None
    if login_column.button("로그인", use_container_width=True):
        action = "login"
    if signup_column.button("회원가입", use_container_width=True):
        action = "signup"

    if not action:
        return
    if not email or not password:
        st.error("이메일과 비밀번호를 모두 입력하세요.")
        return

    try:
        result = api(
            "POST", f"/auth/{action}", json={"email": email, "password": password}
        )
    except ApiError as error:
        st.error(str(error))
        return

    if not result.get("access_token"):
        # 가입은 됐는데 토큰이 없는 경우가 있다 (이메일 확인이 켜져 있을 때).
        st.error("가입은 되었지만 바로 로그인되지 않았습니다. 강사에게 알리세요.")
        return

    st.session_state.access_token = result["access_token"]
    st.session_state.user_email = result["email"]
    st.session_state.expired_notice = None
    st.rerun()


def render_sidebar(options: dict, conversations: list) -> None:
    with st.sidebar:
        st.caption(st.session_state.user_email)
        if st.button("로그아웃", use_container_width=True):
            sign_out()

        st.divider()
        st.subheader("연습 기록")

        if conversations:
            labels = {c["id"]: conversation_label(c) for c in conversations}
            ids = list(labels)
            current = st.session_state.conversation_id
            selected = st.selectbox(
                "지난 연습",
                options=ids,
                format_func=lambda cid: labels[cid],
                index=ids.index(current) if current in ids else 0,
                key="conversation_select",
            )
            st.session_state.conversation_id = selected

            new_title = st.text_input("새 이름", key="rename_input")
            rename_column, delete_column = st.columns(2)
            if rename_column.button("이름 변경", use_container_width=True) and new_title:
                api(
                    "PATCH",
                    f"/me/conversations/{selected}",
                    json={"title": new_title},
                    headers=auth_headers(),
                )
                st.rerun()
            if delete_column.button("삭제", use_container_width=True):
                api("DELETE", f"/me/conversations/{selected}", headers=auth_headers())
                st.session_state.conversation_id = None
                st.rerun()
        else:
            st.caption("아직 연습 기록이 없습니다.")

        st.divider()
        job_title = st.text_input("직무", placeholder="예: 백엔드 개발자")
        if st.button("새 면접 시작", use_container_width=True) and job_title:
            # 주의: user_id 를 보내지 않는다. 서버가 토큰에서 꺼내 쓴다.
            created = api(
                "POST",
                "/me/conversations",
                json={"title": job_title},
                headers=auth_headers(),
            )
            st.session_state.conversation_id = created["id"]
            st.rerun()

        st.divider()
        st.subheader("면접관 설정")
        st.radio("말투", options["tones"], key="tone", horizontal=True)
        st.radio("답변 길이", options["lengths"], key="length", horizontal=True)
        st.caption("고른 값은 다음 질문부터 적용됩니다.")


def render_empty(message: str, hint: str) -> None:
    st.info(message)
    st.caption(hint)


def ask(conversation_id: str, question: str) -> None:
    """질문을 보내고 답이 흘러나오는 것을 보여준다.

    19일차까지는 다 만들어진 뒤에 화면을 새로 그렸다. 몇 초 동안 아무 일도
    일어나지 않는 것처럼 보였다. 오늘은 글자가 나오는 대로 보여준다.
    """
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        try:
            # st.write_stream 은 조각을 받아 화면에 이어 붙이고, 커서도 그려준다.
            st.write_stream(
                stream_answer(
                    f"/conversations/{conversation_id}/chat",
                    {
                        "content": question,
                        "tone": st.session_state.tone,
                        "length": st.session_state.length,
                    },
                    auth_headers(),
                )
            )
        except ApiError as error:
            # 실패한 질문을 기억해 둔다. 다시 시도 버튼이 이것을 쓴다.
            # 사용자가 긴 답변을 다시 타이핑하게 만들면 안 된다.
            st.session_state.failed_question = question
            st.error(str(error))
            return

    st.session_state.failed_question = None
    st.rerun()


def regenerate(conversation_id: str) -> None:
    """마지막 답변을 지우고 새로 받는다.

    다시 시도(Retry)와 다르다.
      다시 시도  — 실패한 요청을 그대로 다시 보낸다. 답이 없는 상태다
      다시 생성  — 성공한 답이 마음에 안 들어 새로 받는다. 기존 답을 지운다
    """
    with st.chat_message("assistant"):
        try:
            st.write_stream(
                stream_answer(
                    f"/conversations/{conversation_id}/regenerate",
                    # 질문은 다시 보내지 않는다. 서버가 마지막 질문을 그대로 쓴다.
                    # 말투와 길이만 보낸다 — 바꿔놓고 다시 생성하는 경우가 많다.
                    {
                        "tone": st.session_state.tone,
                        "length": st.session_state.length,
                    },
                    auth_headers(),
                )
            )
        except ApiError as error:
            st.error(str(error))
            return
    st.rerun()


def render_examples() -> None:
    st.caption("이렇게 시작해 보세요")
    columns = st.columns(len(EXAMPLE_QUESTIONS))
    for column, question in zip(columns, EXAMPLE_QUESTIONS):
        if column.button(question, use_container_width=True):
            st.session_state.pending_question = question
            st.rerun()


def render_follow_ups() -> None:
    """직전 답변을 두고 이어서 할 수 있는 행동.

    17·18일차에는 직전 답변을 질문 안에 통째로 넣어 보냈다.
    오늘부터 면접관이 이전 대화를 기억하므로 그럴 필요가 없다.
    "방금" 이라고만 해도 알아듣는다.
    """
    st.caption("이어서")
    actions = {
        "더 자세히": "방금 한 말을 예시를 들어 더 자세히 설명해 주세요.",
        "간단하게": "방금 한 말을 세 문장으로 줄여 주세요.",
        "다음 질문": "다음 면접 질문을 하나 주세요.",
    }
    columns = st.columns(len(actions))
    for column, (label, question) in zip(columns, actions.items()):
        if column.button(label, use_container_width=True):
            st.session_state.pending_question = question
            st.rerun()


def render_context_controls(conversation_id: str, messages: list, max_history: int) -> None:
    """면접관이 무엇을 기억하는지 보여주고, 끊을 수 있게 한다.

    사용자는 모델이 무엇을 참고하는지 볼 수 없다. 화면이 말해주지 않으면
    "왜 아까 한 말을 기억 못하지" 또는 반대로 "왜 지운 얘기를 계속 하지"가 된다.
    """
    remembered = _remembered_count(messages, max_history)
    reset_column, info_column = st.columns([1, 3])
    if reset_column.button("맥락 초기화", use_container_width=True):
        api(
            "POST",
            f"/conversations/{conversation_id}/reset-context",
            headers=auth_headers(),
        )
        st.rerun()
    info_column.caption(
        f"면접관은 지금 이 대화의 최근 {remembered}개를 기억합니다 "
        f"(최대 {max_history}개). 초기화해도 기록은 남습니다."
    )


def _remembered_count(messages: list, max_history: int) -> int:
    """모델에게 실제로 갈 메시지 수. 백엔드 _build_history 와 같은 순서로 센다."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index]["role"] == "system":
            messages = messages[index + 1 :]
            break
    usable = [m for m in messages if m["role"] in ("user", "assistant")]
    return min(len(usable), max_history)


def render_feedback(conversation_id: str, message_id: str, current: str | None) -> None:
    """이 답변이 도움이 됐는지 묻는다.

    이미 누른 것은 눌린 상태로 보여야 한다. 그렇지 않으면 사용자가
    자기가 평가했는지 기억하지 못하고 계속 다시 누른다.
    """
    up_column, down_column, _ = st.columns([1, 1, 8])
    up_column.button(
        "도움됨",
        key=f"up_{message_id}",
        type="primary" if current == "up" else "secondary",
        on_click=_toggle_feedback,
        args=(conversation_id, message_id, "up", current),
    )
    down_column.button(
        "아쉬움",
        key=f"down_{message_id}",
        type="primary" if current == "down" else "secondary",
        on_click=_toggle_feedback,
        args=(conversation_id, message_id, "down", current),
    )


def _toggle_feedback(conversation_id: str, message_id: str, value: str, current: str | None) -> None:
    # 같은 것을 다시 누르면 취소다. 잘못 누른 것을 되돌릴 수 없으면 안 된다.
    api(
        "POST",
        f"/conversations/{conversation_id}/feedback",
        json={"message_id": message_id, "value": None if current == value else value},
        headers=auth_headers(),
    )


def render_conversation(conversation_id: str, max_history: int) -> None:
    messages = api("GET", f"/conversations/{conversation_id}/messages", headers=auth_headers())
    feedback = api("GET", f"/conversations/{conversation_id}/feedback", headers=auth_headers()) or {}

    if not messages:
        render_empty(
            "아직 주고받은 내용이 없습니다.",
            "아래 예시를 누르거나 직접 입력해서 면접을 시작하세요.",
        )
        render_examples()

    last_index = len(messages) - 1
    for index, message in enumerate(messages):
        if message["role"] == "system":
            # 맥락을 끊은 지점. 말풍선이 아니라 구분선으로 그린다.
            # 누가 한 말이 아니라 "여기서 끊겼다"는 표시이기 때문이다.
            st.divider()
            st.caption(message["content"])
            continue
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message["role"] == "assistant":
                render_feedback(
                    conversation_id, message["id"], feedback.get(message["id"])
                )
                if index == last_index:
                    # 다시 생성은 마지막 답변에만 붙인다. 중간 답변을 다시 만들면
                    # 그 뒤의 대화와 앞뒤가 안 맞게 된다.
                    if st.button("다시 생성", key=f"regen_{message['id']}"):
                        regenerate(conversation_id)

    if st.session_state.failed_question:
        # 답을 못 받은 상태다. 같은 질문을 그대로 다시 보낼 수 있게 한다.
        st.warning("답변을 받지 못했습니다.")
        retry_column, cancel_column, _ = st.columns([1, 1, 6])
        if retry_column.button("다시 시도"):
            question = st.session_state.failed_question
            st.session_state.failed_question = None
            ask(conversation_id, question)
        if cancel_column.button("취소"):
            st.session_state.failed_question = None
            st.rerun()

    if messages:
        render_context_controls(conversation_id, messages, max_history)

    if messages and messages[-1]["role"] == "assistant":
        render_follow_ups()

    if st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None
        ask(conversation_id, question)

    if answer := st.chat_input("답변을 입력하세요"):
        ask(conversation_id, answer)


def render_signed_in() -> None:
    """로그인한 뒤의 화면 전체.

    이 안에서 나는 SessionExpired 는 아래 main 이 한 번에 받는다.
    호출마다 try 를 쓰면 스무 군데가 되고, 한 곳만 빠뜨려도
    거기서 화면이 비어 보인다.
    """
    options = load_options()
    st.session_state.setdefault("tone", options["default_tone"])
    st.session_state.setdefault("length", options["default_length"])

    conversations = api("GET", "/me/conversations", headers=auth_headers())
    render_sidebar(options, conversations)

    st.caption(f"말투 {st.session_state.tone} · 길이 {st.session_state.length}")

    if not conversations:
        render_empty(
            "아직 연습 기록이 없습니다.",
            "왼쪽에서 지원할 직무를 적고 `새 면접 시작` 을 누르세요.",
        )
    # 방어 가지. selectbox 가 첫 항목을 자동으로 고르므로 평소에는 닿지 않는다.
    # 목록이 있는데 선택이 비면 render_conversation(None) 이 되어 422 가 난다.
    elif not st.session_state.conversation_id:
        render_empty(
            "연습할 면접을 고르세요.",
            "왼쪽 `지난 연습` 에서 하나를 선택하면 됩니다.",
        )
    else:
        render_conversation(
            st.session_state.conversation_id, options["max_history_messages"]
        )


st.title(SERVICE_NAME)

try:
    if st.session_state.access_token:
        render_signed_in()
    else:
        render_login()
except SessionExpired as error:
    # 토큰을 지우고 로그인 화면으로 돌린다. 이유는 다음 실행에서 보여준다.
    sign_out(str(error))
except ApiError as error:
    st.error(str(error))