import hmac
import hashlib
import streamlit as st
from portal.backend import call_backend

SUPPORT_EMAIL = "mahajansagar746@gmail.com"
ENTRY_RATE_RS = 0.50
WALLET_MIN_RS = 10
WALLET_MAX_RS = 500
_PERSIST_QP_KEY = "pm_sess"


def _get_session_secret() -> str:
    try:
        if "auth" in st.secrets and st.secrets["auth"].get("cookie_secret"):
            return str(st.secrets["auth"]["cookie_secret"])
    except Exception:
        pass
    return f"policymitra_persist::{SUPPORT_EMAIL}"


def _sign_session_token(auth_method: str, user_id: str, user_email: str) -> str:
    raw = f"{auth_method.strip()}|{user_id.strip()}|{user_email.strip().lower()}"
    sig = hmac.new(
        _get_session_secret().encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:20]
    return f"{auth_method.strip()}:{user_id.strip()}:{sig}"


def _verify_session_token(token: str):
    parts = str(token or "").split(":")
    if len(parts) != 3:
        return None
    auth_method, user_id, sig = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if not auth_method or not user_id or not sig:
        return None
    expected = hmac.new(
        _get_session_secret().encode("utf-8"),
        f"{auth_method}|{user_id}|{user_id.lower()}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:20]
    if not hmac.compare_digest(sig, expected):
        return None
    return auth_method, user_id


def _persist_session_to_url(auth_method: str, user_id: str, user_email: str):
    try:
        st.query_params[_PERSIST_QP_KEY] = _sign_session_token(auth_method, user_id, user_email)
    except Exception:
        pass


def clear_persisted_session():
    try:
        st.query_params.pop(_PERSIST_QP_KEY, None)
    except Exception:
        pass


def apply_login_session(auth_method: str, res: dict, fallback_uid: str = "", fallback_email: str = "", fallback_name: str = ""):
    """Populates Streamlit session state uniformly after Google or Email OTP login."""
    uid = str(res.get("user_id") or fallback_uid or fallback_email).strip()
    uemail = str(res.get("user_email") or fallback_email or "").strip().lower()
    umobile = str(res.get("user_mobile") or "").strip()
    uname = str(res.get("user_name") or fallback_name or uid).strip()
    plan_type = str(res.get("plan_type") or "").strip()
    expiry = str(res.get("expiry") or "").strip()
    wallet_bal = float(res.get("wallet_balance") or 0.0)
    billable = bool(res.get("billable", False))
    trial_expired = bool(res.get("trial_expired", False))

    st.session_state.update({
        "logged_in": True,
        "auth_method": auth_method,
        "user_id": uid,
        "user_email": uemail,
        "user_mobile": umobile,
        "user_name": uname,
        "plan_type": plan_type,
        "expiry": expiry,
        "wallet_balance": wallet_bal,
        "billable": billable,
        "trial_expired": trial_expired,
        "google_auth_error": "",
        "saved_health_rows": None,
        "settings_loaded": False,
        "linked_master_df": None,
        "linked_master_error": "",
        "health_accounts_df": None,
        "motor_accounts_df": None,
        "sme_accounts_df": None,
        "drive_scan_info": None,
        "drive_last_scan_key": "",
        "batch_history": [],
        "round_counter": 0,
        "quick_pdf_bytes_cache": {},
    })
    st.session_state.pop("resolved_bug_notifs", None)
    st.session_state.pop("email_otp_sent_to", None)
    st.session_state.pop("email_otp_name", None)
    _persist_session_to_url(auth_method, uid, uemail)


def restore_email_otp_session_if_present() -> bool:
    """Restores Email OTP login across browser F5 refresh using signed URL query param + backend plan check."""
    if st.session_state.get("logged_in", False):
        if st.session_state.get("auth_method") == "email_otp" and st.session_state.get("user_id"):
            _persist_session_to_url("email_otp", st.session_state["user_id"], st.session_state.get("user_email", ""))
        return True

    try:
        raw_tok = st.query_params.get(_PERSIST_QP_KEY, "")
        if isinstance(raw_tok, list):
            raw_tok = raw_tok[0] if raw_tok else ""
    except Exception:
        raw_tok = ""

    parsed = _verify_session_token(str(raw_tok or ""))
    if not parsed:
        return False

    auth_method, uid = parsed
    if auth_method != "email_otp":
        return False

    res = call_backend({
        "action": "get_wallet_status",
        "user_id": uid,
        "user_email": uid if "@" in uid else "",
        "user_mobile": "",
    })
    if not res.get("success"):
        clear_persisted_session()
        return False

    apply_login_session(
        "email_otp",
        {
            "user_id": uid,
            "user_email": uid if "@" in uid else "",
            "user_name": uid.split("@")[0] if "@" in uid else uid,
            "plan_type": res.get("plan_type", ""),
            "expiry": res.get("expiry", ""),
            "wallet_balance": res.get("wallet_balance", 0.0),
            "billable": res.get("billable", False),
            "trial_expired": res.get("trial_expired", False),
        },
        fallback_uid=uid,
        fallback_email=uid if "@" in uid else "",
    )
    return True


def refresh_wallet_status() -> dict:
    """Fetches latest Plan Type, Expiry & Wallet Balance from Users sheet."""
    res = call_backend({
        "action": "get_wallet_status",
        "user_id": st.session_state.get("user_id", ""),
        "user_email": st.session_state.get("user_email", ""),
        "user_mobile": st.session_state.get("user_mobile", ""),
    })
    if res.get("success"):
        st.session_state["plan_type"] = str(res.get("plan_type") or st.session_state.get("plan_type", ""))
        st.session_state["expiry"] = str(res.get("expiry") or st.session_state.get("expiry", ""))
        st.session_state["wallet_balance"] = float(res.get("wallet_balance") or 0.0)
        st.session_state["billable"] = bool(res.get("billable", False))
        st.session_state["trial_expired"] = bool(res.get("trial_expired", False))
    return res


def render_wallet_banner_if_billable(key_prefix: str = "wl"):
    """
    Shows Wallet Balance + ₹10–₹500 Recharge form ONLY for Paid / Trial-Expired users.
    Lifetime Free and active 7-Day Free Trial users see zero clutter.
    """
    if not st.session_state.get("billable", False):
        return

    bal = float(st.session_state.get("wallet_balance") or 0.0)
    trial_exp = bool(st.session_state.get("trial_expired", False))
    entries_left = int(bal // ENTRY_RATE_RS)

    if trial_exp and bal < ENTRY_RATE_RS:
        st.warning(
            f"⏰ **Your 7 Days Free Trial has ended.** Recharge your Wallet (**₹{WALLET_MIN_RS} – ₹{WALLET_MAX_RS}**) "
            f"to continue at just **₹{ENTRY_RATE_RS:.2f} / correct entry** *(reported bug entries are auto-refunded!)*."
        )
    else:
        c1, c2 = st.columns([3.6, 1.2])
        with c1:
            st.info(
                f"💰 **Wallet Balance: ₹{bal:.2f}** (~{entries_left} entries @ ₹{ENTRY_RATE_RS:.2f}/entry) — "
                f"*Only correct entries are charged; reported bug entries get auto-refunded!*"
            )
        with c2:
            if st.button("🔄 Refresh Wallet", use_container_width=True, key=f"{key_prefix}_refresh_wallet"):
                with st.spinner("Checking wallet..."):
                    refresh_wallet_status()
                st.rerun()

    with st.expander(f"💳 Add Wallet Balance (Min ₹{WALLET_MIN_RS} / Max ₹{WALLET_MAX_RS})", expanded=(bal < ENTRY_RATE_RS)):
        st.caption(
            f"Pay between **₹{WALLET_MIN_RS}** and **₹{WALLET_MAX_RS}** via UPI, then submit your Amount & UPI Ref / UTR below. "
            f"For any payment query, mail **{SUPPORT_EMAIL}**."
        )
        with st.form(f"{key_prefix}_wallet_recharge_form"):
            r1, r2 = st.columns(2)
            with r1:
                amt = st.number_input(
                    "Recharge Amount (₹)",
                    min_value=WALLET_MIN_RS,
                    max_value=WALLET_MAX_RS,
                    value=100,
                    step=10,
                )
            with r2:
                utr = st.text_input("UPI Reference / UTR Number", placeholder="e.g. 432198765432")
            if st.form_submit_button("📩 Submit Recharge Request", type="primary", use_container_width=True):
                if not utr.strip():
                    st.warning("Please enter your UPI Reference / UTR number.")
                else:
                    with st.spinner("Submitting recharge request..."):
                        req_res = call_backend({
                            "action": "request_wallet_recharge",
                            "user_id": st.session_state.get("user_id", ""),
                            "user_email": st.session_state.get("user_email", ""),
                            "amount": int(amt),
                            "utr": utr.strip(),
                        })
                    if req_res.get("success"):
                        st.success(req_res.get("message", "Recharge request submitted!"))
                    else:
                        st.error(req_res.get("message", "Could not submit recharge request."))


def check_wallet_before_batch(pdf_count: int) -> bool:
    """
    Verifies a billable user has enough wallet balance before starting PDF extraction.
    Returns True if allowed to proceed; False (and shows error) if insufficient balance.
    """
    if not st.session_state.get("billable", False) or pdf_count <= 0:
        return True

    refresh_wallet_status()
    if not st.session_state.get("billable", False):
        return True

    bal = float(st.session_state.get("wallet_balance") or 0.0)
    needed = round(pdf_count * ENTRY_RATE_RS, 2)
    if bal < needed:
        st.error(
            f"❌ **Insufficient Wallet Balance!** Selected **{pdf_count} PDFs** require **₹{needed:.2f}** "
            f"(₹{ENTRY_RATE_RS:.2f}/entry), but available balance is **₹{bal:.2f}**. "
            f"Please recharge **₹{WALLET_MIN_RS} – ₹{WALLET_MAX_RS}** above or select fewer PDFs."
        )
        return False
    return True


def charge_wallet_for_batch(done_count: int, batch_id: str) -> str:
    """
    Deducts ₹0.50 x done_count from a Paid user's wallet after extraction completes.
    Returns a status note string to append to save_msg (empty string for Free/Trial users).
    """
    if not st.session_state.get("billable", False) or done_count <= 0:
        return ""

    res = call_backend({
        "action": "deduct_entry_wallet",
        "user_id": st.session_state.get("user_id", ""),
        "user_email": st.session_state.get("user_email", ""),
        "user_mobile": st.session_state.get("user_mobile", ""),
        "entry_count": int(done_count),
        "batch_id": str(batch_id or ""),
    })
    if res.get("success"):
        charged = float(res.get("charged") or 0.0)
        new_bal = float(res.get("wallet_balance") or 0.0)
        st.session_state["wallet_balance"] = new_bal
        if charged > 0:
            return f"💰 Wallet Charged: ₹{charged:.2f} ({done_count} entries @ ₹{ENTRY_RATE_RS:.2f}) | Balance: ₹{new_bal:.2f}"
    return ""


def render_portal_login_screen(google_configured: bool, google_logged_in: bool, g_email: str):
    """
    Password-less 2-Tab Login Screen:
      1. Google Sign-In (auto-registers new users + sends Welcome Email)
      2. Email OTP (100% free instant 6-digit OTP via Gmail + auto-registers new users)
    """
    _, col2, _ = st.columns([1, 2.2, 1])
    with col2:
        st.title("🛡️ MS.Soft Policy Mitra")
        st.caption("All-in-One Insurance Advisor Automation Suite")

        tab_g, tab_otp = st.tabs([
            "🔵 Google Login",
            "📧 Email OTP",
        ])

        # --- TAB 1: GOOGLE LOGIN ---
        with tab_g:
            if google_logged_in and st.session_state.google_auth_error:
                st.error(f"❌ **{g_email}**: {st.session_state.google_auth_error}")
                if st.button("🔄 Sign in with Another Google Account", type="primary", use_container_width=True):
                    st.session_state.google_auth_error = ""
                    clear_persisted_session()
                    st.logout()
            elif google_configured:
                st.info("✨ **New User?** Just click below — your account starts instantly with a **7 Days Free Trial** & setup guide on Email!")
                if st.button("🔵 Continue with Google", type="primary", use_container_width=True):
                    st.login()
            else:
                st.warning("⚠️ Google Sign-In is not configured in Secrets. Please use the Email OTP tab.")

        # --- TAB 2: EMAIL OTP (FREE & INSTANT) ---
        with tab_otp:
            st.caption("Enter your Email ID to receive an instant 6-digit Login OTP (no password needed).")
            sent_email = st.session_state.get("email_otp_sent_to", "")

            with st.form("email_send_otp_form"):
                otp_name = st.text_input(
                    "Your Name (for new users)",
                    value=st.session_state.get("email_otp_name", ""),
                    placeholder="e.g. Rahul Sharma",
                )
                otp_email = st.text_input(
                    "Email ID *",
                    value=sent_email,
                    placeholder="e.g. advisor@gmail.com",
                )
                btn_lbl = "🔄 Resend Email OTP" if sent_email else "📩 Send Email OTP"
                if st.form_submit_button(btn_lbl, type="primary", use_container_width=True):
                    clean_em = otp_email.strip().lower()
                    if not clean_em or "@" not in clean_em or "." not in clean_em.split("@")[-1]:
                        st.warning("Please enter a valid Email ID.")
                    else:
                        with st.spinner("Sending 6-digit OTP to your Email..."):
                            otp_res = call_backend({"action": "send_email_otp", "email": clean_em})
                        if otp_res.get("success"):
                            st.session_state["email_otp_sent_to"] = clean_em
                            st.session_state["email_otp_name"] = otp_name.strip()
                            st.session_state["email_otp_notice"] = otp_res.get("message", f"OTP sent to {clean_em}!")
                            st.rerun()
                        else:
                            st.error(otp_res.get("message", "Could not send Email OTP."))

            if st.session_state.get("email_otp_sent_to"):
                if st.session_state.get("email_otp_notice"):
                    st.success(f"✅ {st.session_state['email_otp_notice']} *(Check Spam/Promotions if not in Inbox)*")
                with st.form("email_verify_otp_form"):
                    otp_code = st.text_input("Enter 6-Digit Email OTP", max_chars=6, placeholder="123456")
                    if st.form_submit_button("✅ Verify OTP & Login", type="primary", use_container_width=True):
                        if not otp_code.strip():
                            st.warning("Please enter the 6-digit OTP sent to your email.")
                        else:
                            with st.spinner("Verifying OTP..."):
                                v_res = call_backend({
                                    "action": "verify_email_otp",
                                    "email": st.session_state["email_otp_sent_to"],
                                    "otp": otp_code.strip(),
                                    "name": st.session_state.get("email_otp_name", ""),
                                })
                            if v_res.get("success"):
                                st.session_state.pop("email_otp_notice", None)
                                apply_login_session(
                                    "email_otp",
                                    v_res,
                                    fallback_uid=v_res.get("user_id", st.session_state["email_otp_sent_to"]),
                                    fallback_email=st.session_state["email_otp_sent_to"],
                                    fallback_name=st.session_state.get("email_otp_name", ""),
                                )
                                st.rerun()
                            else:
                                st.error(v_res.get("message", "Invalid or expired OTP."))

        st.divider()
        st.markdown(
            "<div style='text-align:center; font-size:0.82rem; color:#475569; "
            "background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:10px 12px;'>"
            "📩 <strong>For any query, please share details on mail:</strong> "
            f"<a href='mailto:{SUPPORT_EMAIL}' style='color:#1d4ed8; font-weight:600; text-decoration:none;'>{SUPPORT_EMAIL}</a>"
            "</div>",
            unsafe_allow_html=True,
        )
