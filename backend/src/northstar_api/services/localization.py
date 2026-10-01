from __future__ import annotations

import re
from typing import Any

_LOCALES: dict[str, dict[str, Any]] = {
    "English": {
        "welcomeTitle": "How can I help you?",
        "welcomeMessage": "Ask a question and I'll find the most useful answer.",
        "placeholder": "Ask me anything...",
        "suggestedQuestions": [
            "What services do you offer?",
            "How can I contact support?",
            "Tell me about your plans.",
        ],
        "translations": {
            "newConversation": "New conversation",
            "sendButton": "Send",
            "closeChat": "Close chat",
            "offlineMessage": "We'll be back soon",
        },
        "noEvidence": "I don't have enough verified information to answer that.",
        "providerFallback": "I found relevant information in the connected knowledge base, but I can't generate a reliable answer right now. Please try again.",
        "consentMessage": "I agree that my messages may be processed to answer my request.",
    },
    "Hindi": {
        "welcomeTitle": "मैं आपकी कैसे मदद कर सकता हूँ?",
        "welcomeMessage": "कोई सवाल पूछें, मैं सबसे उपयोगी जवाब ढूँढूँगा।",
        "placeholder": "कुछ भी पूछें...",
        "suggestedQuestions": [
            "आप कौन-सी सेवाएँ देते हैं?",
            "मैं सहायता से कैसे संपर्क करूँ?",
            "अपनी योजनाओं के बारे में बताएं।",
        ],
        "translations": {
            "newConversation": "नई बातचीत",
            "sendButton": "भेजें",
            "closeChat": "चैट बंद करें",
            "offlineMessage": "हम जल्द वापस आएंगे",
        },
        "noEvidence": "मेरे पास इसका जवाब देने के लिए पर्याप्त सत्यापित जानकारी नहीं है।",
        "providerFallback": "मुझे जुड़े ज्ञान आधार में उपयोगी जानकारी मिली है, लेकिन मैं अभी विश्वसनीय जवाब तैयार नहीं कर सकता। कृपया फिर से कोशिश करें।",
        "consentMessage": "मैं सहमत हूँ कि मेरे अनुरोध का जवाब देने के लिए मेरे संदेशों को संसाधित किया जा सकता है।",
    },
    "Spanish": {
        "welcomeTitle": "¿Cómo puedo ayudarte?",
        "welcomeMessage": "Haz una pregunta y encontraré la respuesta más útil.",
        "placeholder": "Pregúntame lo que quieras...",
        "suggestedQuestions": [
            "¿Qué servicios ofrecen?",
            "¿Cómo contacto con soporte?",
            "Cuéntame sobre sus planes.",
        ],
        "translations": {
            "newConversation": "Nueva conversación",
            "sendButton": "Enviar",
            "closeChat": "Cerrar chat",
            "offlineMessage": "Volveremos pronto",
        },
        "noEvidence": "No tengo suficiente información verificada para responder.",
        "providerFallback": "Encontré información relevante en la base de conocimiento, pero ahora no puedo generar una respuesta fiable. Inténtalo de nuevo.",
        "consentMessage": "Acepto que mis mensajes se procesen para responder a mi solicitud.",
    },
    "French": {
        "welcomeTitle": "Comment puis-je vous aider ?",
        "welcomeMessage": "Posez une question et je trouverai la réponse la plus utile.",
        "placeholder": "Posez-moi une question...",
        "suggestedQuestions": [
            "Quels services proposez-vous ?",
            "Comment contacter le support ?",
            "Parlez-moi de vos offres.",
        ],
        "translations": {
            "newConversation": "Nouvelle conversation",
            "sendButton": "Envoyer",
            "closeChat": "Fermer le chat",
            "offlineMessage": "Nous revenons bientôt",
        },
        "noEvidence": "Je n'ai pas assez d'informations vérifiées pour répondre.",
        "providerFallback": "J'ai trouvé des informations pertinentes dans la base de connaissances, mais je ne peux pas produire une réponse fiable maintenant. Veuillez réessayer.",
        "consentMessage": "J'accepte que mes messages soient traités pour répondre à ma demande.",
    },
    "German": {
        "welcomeTitle": "Wie kann ich Ihnen helfen?",
        "welcomeMessage": "Stellen Sie eine Frage und ich finde die hilfreichste Antwort.",
        "placeholder": "Fragen Sie mich etwas...",
        "suggestedQuestions": [
            "Welche Dienstleistungen bieten Sie an?",
            "Wie kann ich den Support kontaktieren?",
            "Erzählen Sie mir von Ihren Tarifen.",
        ],
        "translations": {
            "newConversation": "Neue Unterhaltung",
            "sendButton": "Senden",
            "closeChat": "Chat schließen",
            "offlineMessage": "Wir sind bald zurück",
        },
        "noEvidence": "Ich habe nicht genügend verifizierte Informationen für eine Antwort.",
        "providerFallback": "Ich habe passende Informationen in der Wissensbasis gefunden, kann aber gerade keine verlässliche Antwort erstellen. Bitte versuchen Sie es erneut.",
        "consentMessage": "Ich stimme zu, dass meine Nachrichten zur Beantwortung meiner Anfrage verarbeitet werden.",
    },
    "Arabic": {
        "welcomeTitle": "كيف يمكنني مساعدتك؟",
        "welcomeMessage": "اطرح سؤالًا وسأجد لك الإجابة الأكثر فائدة.",
        "placeholder": "اسألني أي شيء...",
        "suggestedQuestions": [
            "ما الخدمات التي تقدمونها؟",
            "كيف أتواصل مع الدعم؟",
            "أخبرني عن خططكم.",
        ],
        "translations": {
            "newConversation": "محادثة جديدة",
            "sendButton": "إرسال",
            "closeChat": "إغلاق المحادثة",
            "offlineMessage": "سنعود قريبًا",
        },
        "noEvidence": "ليست لدي معلومات موثقة كافية للإجابة عن ذلك.",
        "providerFallback": "وجدت معلومات ذات صلة في قاعدة المعرفة، لكن لا يمكنني إنشاء إجابة موثوقة الآن. يرجى المحاولة مرة أخرى.",
        "consentMessage": "أوافق على معالجة رسائلي للرد على طلبي.",
    },
}


def agent_locale(language: str) -> dict[str, Any]:
    return _LOCALES.get(language, _LOCALES["English"])


def localized_appearance(language: str) -> dict[str, Any]:
    locale = agent_locale(language)
    return {
        "welcomeTitle": locale["welcomeTitle"],
        "welcomeMessage": locale["welcomeMessage"],
        "placeholder": locale["placeholder"],
        "suggestedQuestions": list(locale["suggestedQuestions"]),
        "translations": dict(locale["translations"]),
        "interfaceLanguage": language,
        "textDirection": "rtl" if language == "Arabic" else "ltr",
        "consentMessage": locale["consentMessage"],
    }


def localized_no_evidence(language: str) -> str:
    return str(agent_locale(language)["noEvidence"])


def localized_provider_fallback(language: str) -> str:
    return str(agent_locale(language)["providerFallback"])


def localized_question_fallback(question: str, language: str) -> str:
    value = re.sub(r"[^a-z0-9\s]", "", question.casefold())
    value = re.sub(r"\s+", " ", value).strip()
    phrases: dict[str, dict[str, str]] = {
        "Hindi": {
            "hi": "\u0928\u092e\u0938\u094d\u0924\u0947",
            "hii": "\u0928\u092e\u0938\u094d\u0924\u0947",
            "hello": "\u0928\u092e\u0938\u094d\u0924\u0947",
            "what services do you offer": "\u0906\u092a \u0915\u094c\u0928-\u0938\u0940 \u0938\u0947\u0935\u093e\u090f\u0901 \u0926\u0947\u0924\u0947 \u0939\u0948\u0902?",
            "how can i contact support": "\u092e\u0948\u0902 \u0938\u0939\u093e\u092f\u0924\u093e \u0938\u0947 \u0915\u0948\u0938\u0947 \u0938\u0902\u092a\u0930\u094d\u0915 \u0915\u0930\u0942\u0901?",
            "tell me about your plans": "\u0905\u092a\u0928\u0940 \u092f\u094b\u091c\u0928\u093e\u0913\u0902 \u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 \u092c\u0924\u093e\u090f\u0901\u0964",
            "what is cse": "\u0938\u0940\u090f\u0938\u0908 \u0915\u094d\u092f\u093e \u0939\u0948?",
        },
        "Spanish": {"hi": "Hola", "hii": "Hola", "hello": "Hola"},
        "French": {"hi": "Bonjour", "hii": "Bonjour", "hello": "Bonjour"},
        "German": {"hi": "Hallo", "hii": "Hallo", "hello": "Hallo"},
        "Arabic": {
            "hi": "\u0645\u0631\u062d\u0628\u064b\u0627",
            "hii": "\u0645\u0631\u062d\u0628\u064b\u0627",
            "hello": "\u0645\u0631\u062d\u0628\u064b\u0627",
        },
    }
    return phrases.get(language, {}).get(value, question.strip())
