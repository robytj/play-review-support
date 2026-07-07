"""i18n for the public support site (SPEC-02 / SPEC-02a §8).

STRINGS is extracted VERBATIM from templates/web/_strings.html -- the design
package's documented source of truth for every UI key (DESIGN-NOTES.md decision 1:
"move it to i18n.py at integration"; this module is that move). If a key is edited
here, mirror it in _strings.html so the design docs don't drift.

Semantics per the design notes:
  - en is the complete dict and the fallback for every other language
    (pt-BR / es / ar deliberately carry only the keys that were translated).
  - interpolation is .format()-style: t('count.articles', n=3) -> "3 articles".
  - ar is the only RTL language ("dir" is derived in app/web_support.py).
"""

LANGS = ("en", "pt-BR", "es", "ar")
RTL_LANGS = ("ar",)

# Site language -> kb_translations.lang key (app/db.py: 'pt' | 'es' | 'ar').
KB_TRANSLATION_LANG = {"pt-BR": "pt", "es": "es", "ar": "ar"}

STRINGS = {
    "en": {
        "brand.support": "SUPPORT",
        "nav.lang": "EN",
        "chip.add_sid": "ADD SID",
        "chip.guest": "GUEST",
        "search.placeholder": "SEARCH HELP…",
        "search.submit": "Search",
        "home.eyebrow": "PRIME RUSH — PLAYER SUPPORT",
        "home.h1": "How can we help?",
        "home.categories": "BROWSE BY TOPIC",
        "home.popular": "POPULAR ARTICLES",
        "cat.account": "Account & Login",
        "cat.payments": "Payments & Purchases",
        "cat.gameplay": "Gameplay & Progression",
        "cat.bans": "Bans & Fair Play",
        "cat.technical": "Technical Issues",
        "cat.updates": "Updates & Patches",
        "cat.rewards": "Rewards & Events",
        "cat.general": "General",
        "count.articles": "{n} articles",
        "cta.title": "Still need help?",
        "cta.sub": "Usually replies instantly",
        "cta.chat": "Chat with us",
        "cta.email": "Email us",
        "cta.email_note": "Chat is offline right now — we'll reply by email.",
        "vote.q": "Was this helpful?",
        "vote.thanks": "Thanks for the feedback.",
        "vote.no_followup": "Sorry that didn't land. Want to ask us directly?",
        "article.related": "RELATED ARTICLES",
        "article.translate": "TRANSLATE",
        "article.translated": "Translated",
        "article.view_original": "view original",
        "search.results": "{n} results for “{q}”",
        "search.empty_title": "No results",
        "search.empty_sub": "No results. Try the category list, or just ask us.",
        "search.back": "Back to help",
        "chat.title": "PRIME RUSH SUPPORT",
        "chat.placeholder": "Type your message…",
        "chat.send": "Send",
        "chat.new_reply": "↓ new reply",
        "chat.offline": "You're offline — reconnecting…",
        "chat.unavailable": "Chat is busy — browse help articles or leave a ticket.",
        "chat.link_account": "LINK ACCOUNT",
        "chat.add_sid_prompt": "Add your SID to unlock account help.",
        "chat.dismiss": "Dismiss",
        "chat.sid_chip": "Add SID for account help",
        "chat.escalated_title": "A human will take it from here.",
        "chat.escalated_sub": "We'll reply here and at your ticket page.",
        "chat.csat_q": "Did this solve it?",
        "chat.resolved": "Glad that's sorted.",
        "chat.we_know": "WHAT WE CAN SEE",
        "chat.edit": "EDIT",
        "chat.copy": "COPY",
        "chat.copied": "Copied",
        "chat.redeem": "REDEEM IN STORE",
        "chat.expires": "Expires {date}",
        "identity.headline": "Link your player account",
        "identity.headline_confirm": "Confirm your player ID",
        "identity.sid_label": "PLAYER SID",
        "identity.sid_placeholder": "PR-XXXX-XXXX",
        "identity.or": "or registered email",
        "identity.email_label": "EMAIL",
        "identity.continue": "Continue",
        "identity.skip": "Continue without SID",
        "identity.wheres_sid": "Where's my SID?",
        "identity.step1": "Open Prime Rush and tap Settings (gear, top-right).",
        "identity.step2": "Tap your profile name to open the Profile panel.",
        "identity.step3": "Your SID is under the avatar — tap to copy it.",
        "identity.err_format": "That doesn't look like a SID. Check the format PR-XXXX-XXXX.",
        "identity.err_notfound": "We couldn't find that account. Try your registered email.",
        "identity.linked": "Account linked",
        "ticket.status.open": "OPEN",
        "ticket.status.answered": "ANSWERED",
        "ticket.status.escalated": "ESCALATED",
        "ticket.status.resolved": "RESOLVED",
        "ticket.status.closed": "CLOSED",
        "ticket.you": "YOU",
        "ticket.staff": "PRIME RUSH SUPPORT",
        "ticket.reply_placeholder": "Add a reply…",
        "ticket.closed_cta": "This ticket is closed — start a new chat",
        "err.404_title": "Lost in the drop zone",
        "err.404_sub": "That page dropped off the map.",
        "err.500_title": "Something broke on our end",
        "err.500_sub": "We're on it. Try again in a moment.",
        "footer.privacy": "Privacy",
        "footer.terms": "Terms",
        "footer.store": "store.primerush.gg",
        "footer.copy": "© SuperGaming",
    },
    "pt-BR": {
        "brand.support": "SUPORTE", "chip.add_sid": "ADD SID", "chip.guest": "VISITANTE",
        "search.placeholder": "BUSCAR AJUDA…", "home.eyebrow": "PRIME RUSH — SUPORTE AO JOGADOR",
        "home.h1": "Como podemos ajudar?", "home.categories": "NAVEGAR POR TÓPICO",
        "home.popular": "ARTIGOS POPULARES", "cat.account": "Conta e Login",
        "cat.payments": "Pagamentos e Compras", "cat.gameplay": "Jogo e Progressão",
        "cat.bans": "Banimentos e Jogo Limpo", "cat.technical": "Problemas Técnicos",
        "cat.updates": "Atualizações e Patches", "cat.rewards": "Recompensas e Eventos",
        "cat.general": "Geral", "count.articles": "{n} artigos", "cta.title": "Ainda precisa de ajuda?",
        "cta.sub": "Costuma responder na hora", "cta.chat": "Fale conosco", "cta.email": "Envie um e-mail",
        "vote.q": "Isto foi útil?", "vote.thanks": "Obrigado pelo retorno.",
        "vote.no_followup": "Que pena. Quer perguntar direto pra gente?",
        "article.related": "ARTIGOS RELACIONADOS", "article.translate": "TRADUZIR",
        "search.results": "{n} resultados para “{q}”", "search.empty_title": "Nenhum resultado",
        "search.empty_sub": "Nada encontrado. Veja a lista de categorias, ou pergunte pra gente.",
        "search.back": "Voltar à ajuda", "chat.title": "SUPORTE PRIME RUSH",
        "chat.placeholder": "Digite sua mensagem…", "chat.escalated_title": "Um humano vai assumir daqui.",
        "chat.csat_q": "Isto resolveu?", "chat.resolved": "Que bom que resolveu.",
        "identity.headline": "Vincule sua conta de jogador", "identity.continue": "Continuar",
        "identity.skip": "Continuar sem SID", "identity.wheres_sid": "Onde está meu SID?",
        "identity.linked": "Conta vinculada", "ticket.you": "VOCÊ", "ticket.staff": "SUPORTE PRIME RUSH",
        "err.404_title": "Perdido na zona de queda", "footer.copy": "© SuperGaming",
    },
    "es": {
        "brand.support": "SOPORTE", "chip.add_sid": "AÑADIR SID", "chip.guest": "INVITADO",
        "search.placeholder": "BUSCAR AYUDA…", "home.eyebrow": "PRIME RUSH — SOPORTE AL JUGADOR",
        "home.h1": "¿Cómo podemos ayudarte?", "home.categories": "EXPLORAR POR TEMA",
        "home.popular": "ARTÍCULOS POPULARES", "cat.account": "Cuenta e inicio de sesión",
        "cat.payments": "Pagos y compras", "cat.gameplay": "Juego y progresión",
        "cat.bans": "Baneos y juego limpio", "cat.technical": "Problemas técnicos",
        "cat.updates": "Actualizaciones y parches", "cat.rewards": "Recompensas y eventos",
        "cat.general": "General", "count.articles": "{n} artículos", "cta.title": "¿Aún necesitas ayuda?",
        "cta.sub": "Suele responder al instante", "cta.chat": "Chatea con nosotros", "cta.email": "Escríbenos",
        "vote.q": "¿Te resultó útil?", "vote.thanks": "Gracias por tu opinión.",
        "vote.no_followup": "Lo sentimos. ¿Quieres preguntarnos directamente?",
        "article.related": "ARTÍCULOS RELACIONADOS", "article.translate": "TRADUCIR",
        "search.results": "{n} resultados para “{q}”", "search.empty_title": "Sin resultados",
        "search.empty_sub": "Sin resultados. Prueba la lista de categorías, o pregúntanos.",
        "search.back": "Volver a la ayuda", "chat.title": "SOPORTE PRIME RUSH",
        "chat.placeholder": "Escribe tu mensaje…", "chat.escalated_title": "Una persona lo tomará desde aquí.",
        "chat.csat_q": "¿Esto lo resolvió?", "chat.resolved": "Me alegra que se resolviera.",
        "identity.headline": "Vincula tu cuenta de jugador", "identity.continue": "Continuar",
        "identity.skip": "Continuar sin SID", "identity.wheres_sid": "¿Dónde está mi SID?",
        "identity.linked": "Cuenta vinculada", "ticket.you": "TÚ", "ticket.staff": "SOPORTE PRIME RUSH",
        "err.404_title": "Perdido en la zona de caída", "footer.copy": "© SuperGaming",
    },
    "ar": {
        "brand.support": "الدعم", "chip.add_sid": "إضافة SID", "chip.guest": "زائر",
        "search.placeholder": "ابحث في المساعدة…", "home.eyebrow": "PRIME RUSH — دعم اللاعبين",
        "home.h1": "كيف يمكننا المساعدة؟", "home.categories": "تصفّح حسب الموضوع",
        "home.popular": "المقالات الشائعة", "cat.account": "الحساب وتسجيل الدخول",
        "cat.payments": "المدفوعات والمشتريات", "cat.gameplay": "اللعب والتقدّم",
        "cat.bans": "الحظر واللعب النزيه", "cat.technical": "المشاكل التقنية",
        "cat.updates": "التحديثات والتصحيحات", "cat.rewards": "المكافآت والفعاليات",
        "cat.general": "عام", "count.articles": "{n} مقالات", "cta.title": "ما زلت بحاجة إلى مساعدة؟",
        "cta.sub": "يردّ عادةً على الفور", "cta.chat": "تحدّث معنا", "cta.email": "راسلنا",
        "vote.q": "هل كان هذا مفيدًا؟", "vote.thanks": "شكرًا على ملاحظاتك.",
        "vote.no_followup": "نأسف لذلك. هل تريد أن تسألنا مباشرةً؟",
        "article.related": "مقالات ذات صلة", "article.translate": "ترجمة",
        "search.results": "{n} نتائج عن ”{q}“", "search.empty_title": "لا نتائج",
        "search.empty_sub": "لا نتائج. جرّب قائمة الفئات، أو اسألنا مباشرةً.",
        "search.back": "العودة إلى المساعدة", "chat.title": "دعم PRIME RUSH",
        "chat.placeholder": "اكتب رسالتك…", "chat.escalated_title": "سيتولّى الأمر شخص حقيقي من هنا.",
        "chat.csat_q": "هل حلّ هذا المشكلة؟", "chat.resolved": "يسعدنا أنّ الأمر حُلّ.",
        "identity.headline": "اربط حساب اللاعب الخاص بك", "identity.continue": "متابعة",
        "identity.skip": "المتابعة بدون SID", "identity.wheres_sid": "أين رقم SID الخاص بي؟",
        "identity.linked": "تم ربط الحساب", "ticket.you": "أنت", "ticket.staff": "دعم PRIME RUSH",
        "err.404_title": "ضائع في منطقة الإنزال", "footer.copy": "© SuperGaming",
    },
}


def translate(lang: str, key: str, **fmt) -> str:
    """t('key', **fmt) with English fallback (SPEC-02a §8). Unknown key returns
    the key itself -- a loud-but-not-crashing marker John can spot in review."""
    s = STRINGS.get(lang, {}).get(key)
    if s is None:
        s = STRINGS["en"].get(key, key)
    if fmt:
        try:
            s = s.format(**fmt)
        except (KeyError, IndexError):
            pass
    return s


def make_t(lang: str):
    """Bound t() registered into the Jinja render context per request."""
    def t(key: str, **fmt) -> str:
        return translate(lang, key, **fmt)
    return t


def normalize_lang(value: str | None) -> str | None:
    """'pt-BR' | 'es' | 'ar' | 'en' (case-tolerant); None if unrecognized."""
    if not value:
        return None
    low = value.strip().lower()
    for lang in LANGS:
        if low == lang.lower():
            return lang
    if low.startswith("pt"):
        return "pt-BR"
    return None
