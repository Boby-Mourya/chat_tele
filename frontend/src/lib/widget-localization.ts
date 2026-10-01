import type { AgentAppearance } from '@/types';

type WidgetTranslations = NonNullable<AgentAppearance['translations']>;

export interface WidgetLocale {
  translations: WidgetTranslations;
  welcomeTitle: string;
  welcomeMessage: string;
  placeholder: string;
  suggestedQuestions: string[];
  today: string;
  safetyNotice: string;
  poweredBy: string;
  moreOptions: string;
  voiceInput: string;
  acceptConsent: string;
  privacyPolicy: string;
  continueLabel: string;
}

export const supportedWidgetLanguages = ['English', 'Hindi', 'Spanish', 'French', 'German', 'Arabic'] as const;
export type WidgetLanguage = typeof supportedWidgetLanguages[number];

export interface ChatUiLocale {
  copyConversation: string;
  conversationCopied: string;
  openChat: string;
  message: string;
  sessionError: string;
  responseError: string;
  tryAgain: string;
  positiveFeedback: string;
  helpful: string;
  negativeFeedback: string;
  notHelpful: string;
  regenerateAnswer: string;
  regenerate: string;
  feedbackTitle: string;
  closeFeedback: string;
  feedbackQuestion: string;
  reason: string;
  selectReason: string;
  incorrectAnswer: string;
  incompleteAnswer: string;
  hallucinatedResponse: string;
  irrelevantAnswer: string;
  other: string;
  additionalComments: string;
  commentsPlaceholder: string;
  cancel: string;
  submitFeedback: string;
  consentMessage: string;
  searchChats: string;
  searchMessages: string;
  activeNow: string;
  online: string;
  businessAccount: string;
  professionalAccount: string;
  aiAssistant: string;
  incomingMessage: string;
  responseDelivered: string;
  livePreview: string;
}

const locales: Record<string, WidgetLocale> = {
  English: {
    translations: { newConversation: 'New conversation', sendButton: 'Send', closeChat: 'Close chat', offlineMessage: "We'll be back soon" },
    welcomeTitle: 'How can I help you?', welcomeMessage: 'Ask a question and I’ll find the most useful answer.', placeholder: 'Ask me anything…',
    suggestedQuestions: ['What services do you offer?', 'How can I contact support?', 'Tell me about your plans.'],
    today: 'Today', safetyNotice: 'AI can make mistakes. Check important information.', poweredBy: 'Powered by', moreOptions: 'More options', voiceInput: 'Voice input', acceptConsent: 'Accept consent to start chatting', privacyPolicy: 'Privacy policy', continueLabel: 'Continue',
  },
  Hindi: {
    translations: { newConversation: 'नई बातचीत', sendButton: 'भेजें', closeChat: 'चैट बंद करें', offlineMessage: 'हम जल्द वापस आएंगे' },
    welcomeTitle: 'मैं आपकी कैसे मदद कर सकता हूँ?', welcomeMessage: 'कोई सवाल पूछें, मैं सबसे उपयोगी जवाब ढूँढूँगा।', placeholder: 'कुछ भी पूछें…',
    suggestedQuestions: ['आप कौन-सी सेवाएँ देते हैं?', 'मैं सहायता से कैसे संपर्क करूँ?', 'अपनी योजनाओं के बारे में बताएं।'],
    today: 'आज', safetyNotice: 'एआई से गलतियाँ हो सकती हैं। महत्वपूर्ण जानकारी जाँचें।', poweredBy: 'द्वारा संचालित', moreOptions: 'अधिक विकल्प', voiceInput: 'वॉइस इनपुट', acceptConsent: 'चैट शुरू करने के लिए सहमति दें', privacyPolicy: 'गोपनीयता नीति', continueLabel: 'जारी रखें',
  },
  Spanish: {
    translations: { newConversation: 'Nueva conversación', sendButton: 'Enviar', closeChat: 'Cerrar chat', offlineMessage: 'Volveremos pronto' },
    welcomeTitle: '¿Cómo puedo ayudarte?', welcomeMessage: 'Haz una pregunta y encontraré la respuesta más útil.', placeholder: 'Pregúntame lo que quieras…',
    suggestedQuestions: ['¿Qué servicios ofrecen?', '¿Cómo contacto con soporte?', 'Cuéntame sobre sus planes.'],
    today: 'Hoy', safetyNotice: 'La IA puede cometer errores. Verifica la información importante.', poweredBy: 'Desarrollado por', moreOptions: 'Más opciones', voiceInput: 'Entrada de voz', acceptConsent: 'Acepta el consentimiento para comenzar', privacyPolicy: 'Política de privacidad', continueLabel: 'Continuar',
  },
  French: {
    translations: { newConversation: 'Nouvelle conversation', sendButton: 'Envoyer', closeChat: 'Fermer le chat', offlineMessage: 'Nous revenons bientôt' },
    welcomeTitle: 'Comment puis-je vous aider ?', welcomeMessage: 'Posez une question et je trouverai la réponse la plus utile.', placeholder: 'Posez-moi une question…',
    suggestedQuestions: ['Quels services proposez-vous ?', 'Comment contacter le support ?', 'Parlez-moi de vos offres.'],
    today: "Aujourd’hui", safetyNotice: "L’IA peut faire des erreurs. Vérifiez les informations importantes.", poweredBy: 'Propulsé par', moreOptions: 'Plus d’options', voiceInput: 'Saisie vocale', acceptConsent: 'Acceptez le consentement pour commencer', privacyPolicy: 'Politique de confidentialité', continueLabel: 'Continuer',
  },
  German: {
    translations: { newConversation: 'Neue Unterhaltung', sendButton: 'Senden', closeChat: 'Chat schließen', offlineMessage: 'Wir sind bald zurück' },
    welcomeTitle: 'Wie kann ich Ihnen helfen?', welcomeMessage: 'Stellen Sie eine Frage und ich finde die hilfreichste Antwort.', placeholder: 'Fragen Sie mich etwas…',
    suggestedQuestions: ['Welche Dienstleistungen bieten Sie an?', 'Wie kann ich den Support kontaktieren?', 'Erzählen Sie mir von Ihren Tarifen.'],
    today: 'Heute', safetyNotice: 'KI kann Fehler machen. Prüfen Sie wichtige Informationen.', poweredBy: 'Bereitgestellt von', moreOptions: 'Weitere Optionen', voiceInput: 'Spracheingabe', acceptConsent: 'Stimmen Sie zu, um den Chat zu starten', privacyPolicy: 'Datenschutzrichtlinie', continueLabel: 'Weiter',
  },
  Arabic: {
    translations: { newConversation: 'محادثة جديدة', sendButton: 'إرسال', closeChat: 'إغلاق المحادثة', offlineMessage: 'سنعود قريبًا' },
    welcomeTitle: 'كيف يمكنني مساعدتك؟', welcomeMessage: 'اطرح سؤالًا وسأجد لك الإجابة الأكثر فائدة.', placeholder: 'اسألني أي شيء…',
    suggestedQuestions: ['ما الخدمات التي تقدمونها؟', 'كيف أتواصل مع الدعم؟', 'أخبرني عن خططكم.'],
    today: 'اليوم', safetyNotice: 'قد يرتكب الذكاء الاصطناعي أخطاء. تحقق من المعلومات المهمة.', poweredBy: 'مدعوم من', moreOptions: 'المزيد من الخيارات', voiceInput: 'إدخال صوتي', acceptConsent: 'وافق على الشروط لبدء المحادثة', privacyPolicy: 'سياسة الخصوصية', continueLabel: 'متابعة',
  },
};

const chatUiLocales: Record<string, ChatUiLocale> = {
  English: {
    copyConversation: 'Copy conversation', conversationCopied: 'Conversation copied',
    openChat: 'Open chat with', message: 'Message', sessionError: 'I could not start a new conversation.', responseError: 'I could not complete that response.', tryAgain: 'Please try again.', positiveFeedback: 'Positive feedback', helpful: 'Helpful', negativeFeedback: 'Negative feedback', notHelpful: 'Not helpful', regenerateAnswer: 'Regenerate answer', regenerate: 'Regenerate', feedbackTitle: 'Help us improve', closeFeedback: 'Close feedback', feedbackQuestion: 'What was wrong with this answer?', reason: 'Reason', selectReason: 'Select a reason', incorrectAnswer: 'Incorrect answer', incompleteAnswer: 'Incomplete answer', hallucinatedResponse: 'Made-up information', irrelevantAnswer: 'Irrelevant answer', other: 'Other', additionalComments: 'Additional comments', commentsPlaceholder: 'Tell us more (optional)', cancel: 'Cancel', submitFeedback: 'Submit feedback', consentMessage: 'I agree that my messages may be processed to answer my request.', searchChats: 'Search chats', searchMessages: 'Search messages', activeNow: 'Active now', online: 'online', businessAccount: 'Business account', professionalAccount: 'Professional account', aiAssistant: 'AI customer assistant', incomingMessage: 'Incoming message', responseDelivered: 'Response delivered', livePreview: 'Live preview',
  },
  Hindi: {
    copyConversation: 'बातचीत कॉपी करें', conversationCopied: 'बातचीत कॉपी हो गई',
    openChat: 'चैट खोलें:', message: 'संदेश', sessionError: 'नई बातचीत शुरू नहीं हो सकी।', responseError: 'मैं यह जवाब पूरा नहीं कर सका।', tryAgain: 'कृपया फिर से कोशिश करें।', positiveFeedback: 'सकारात्मक प्रतिक्रिया', helpful: 'सहायक', negativeFeedback: 'नकारात्मक प्रतिक्रिया', notHelpful: 'सहायक नहीं', regenerateAnswer: 'जवाब फिर से बनाएँ', regenerate: 'फिर से बनाएँ', feedbackTitle: 'हमें बेहतर बनाने में मदद करें', closeFeedback: 'प्रतिक्रिया बंद करें', feedbackQuestion: 'इस जवाब में क्या गलत था?', reason: 'कारण', selectReason: 'कारण चुनें', incorrectAnswer: 'गलत जवाब', incompleteAnswer: 'अधूरा जवाब', hallucinatedResponse: 'मनगढ़ंत जानकारी', irrelevantAnswer: 'अप्रासंगिक जवाब', other: 'अन्य', additionalComments: 'अतिरिक्त टिप्पणी', commentsPlaceholder: 'और जानकारी दें (वैकल्पिक)', cancel: 'रद्द करें', submitFeedback: 'प्रतिक्रिया भेजें', consentMessage: 'मैं सहमत हूँ कि मेरे अनुरोध का जवाब देने के लिए मेरे संदेशों को संसाधित किया जा सकता है।', searchChats: 'चैट खोजें', searchMessages: 'संदेश खोजें', activeNow: 'अभी सक्रिय', online: 'ऑनलाइन', businessAccount: 'व्यावसायिक खाता', professionalAccount: 'प्रोफ़ेशनल खाता', aiAssistant: 'एआई ग्राहक सहायक', incomingMessage: 'आने वाला संदेश', responseDelivered: 'जवाब भेजा गया', livePreview: 'लाइव पूर्वावलोकन',
  },
  Spanish: {
    copyConversation: 'Copiar conversación', conversationCopied: 'Conversación copiada',
    openChat: 'Abrir chat con', message: 'Mensaje', sessionError: 'No pude iniciar una nueva conversación.', responseError: 'No pude completar esa respuesta.', tryAgain: 'Inténtalo de nuevo.', positiveFeedback: 'Comentario positivo', helpful: 'Útil', negativeFeedback: 'Comentario negativo', notHelpful: 'No útil', regenerateAnswer: 'Regenerar respuesta', regenerate: 'Regenerar', feedbackTitle: 'Ayúdanos a mejorar', closeFeedback: 'Cerrar comentarios', feedbackQuestion: '¿Qué estaba mal en esta respuesta?', reason: 'Motivo', selectReason: 'Selecciona un motivo', incorrectAnswer: 'Respuesta incorrecta', incompleteAnswer: 'Respuesta incompleta', hallucinatedResponse: 'Información inventada', irrelevantAnswer: 'Respuesta irrelevante', other: 'Otro', additionalComments: 'Comentarios adicionales', commentsPlaceholder: 'Cuéntanos más (opcional)', cancel: 'Cancelar', submitFeedback: 'Enviar comentarios', consentMessage: 'Acepto que mis mensajes se procesen para responder a mi solicitud.', searchChats: 'Buscar chats', searchMessages: 'Buscar mensajes', activeNow: 'Activo ahora', online: 'en línea', businessAccount: 'Cuenta empresarial', professionalAccount: 'Cuenta profesional', aiAssistant: 'Asistente de atención con IA', incomingMessage: 'Mensaje entrante', responseDelivered: 'Respuesta entregada', livePreview: 'Vista previa',
  },
  French: {
    copyConversation: 'Copier la conversation', conversationCopied: 'Conversation copiée',
    openChat: 'Ouvrir le chat avec', message: 'Message', sessionError: 'Je n’ai pas pu démarrer une nouvelle conversation.', responseError: 'Je n’ai pas pu terminer cette réponse.', tryAgain: 'Veuillez réessayer.', positiveFeedback: 'Avis positif', helpful: 'Utile', negativeFeedback: 'Avis négatif', notHelpful: 'Pas utile', regenerateAnswer: 'Régénérer la réponse', regenerate: 'Régénérer', feedbackTitle: 'Aidez-nous à nous améliorer', closeFeedback: 'Fermer les commentaires', feedbackQuestion: 'Quel était le problème avec cette réponse ?', reason: 'Raison', selectReason: 'Choisissez une raison', incorrectAnswer: 'Réponse incorrecte', incompleteAnswer: 'Réponse incomplète', hallucinatedResponse: 'Informations inventées', irrelevantAnswer: 'Réponse non pertinente', other: 'Autre', additionalComments: 'Commentaires supplémentaires', commentsPlaceholder: 'Dites-nous-en plus (facultatif)', cancel: 'Annuler', submitFeedback: 'Envoyer', consentMessage: 'J’accepte que mes messages soient traités pour répondre à ma demande.', searchChats: 'Rechercher des chats', searchMessages: 'Rechercher des messages', activeNow: 'Actif maintenant', online: 'en ligne', businessAccount: 'Compte professionnel', professionalAccount: 'Compte professionnel', aiAssistant: 'Assistant client IA', incomingMessage: 'Message entrant', responseDelivered: 'Réponse envoyée', livePreview: 'Aperçu en direct',
  },
  German: {
    copyConversation: 'Unterhaltung kopieren', conversationCopied: 'Unterhaltung kopiert',
    openChat: 'Chat öffnen mit', message: 'Nachricht', sessionError: 'Ich konnte keine neue Unterhaltung starten.', responseError: 'Ich konnte diese Antwort nicht abschließen.', tryAgain: 'Bitte versuchen Sie es erneut.', positiveFeedback: 'Positives Feedback', helpful: 'Hilfreich', negativeFeedback: 'Negatives Feedback', notHelpful: 'Nicht hilfreich', regenerateAnswer: 'Antwort neu erstellen', regenerate: 'Neu erstellen', feedbackTitle: 'Helfen Sie uns, besser zu werden', closeFeedback: 'Feedback schließen', feedbackQuestion: 'Was war an dieser Antwort falsch?', reason: 'Grund', selectReason: 'Grund auswählen', incorrectAnswer: 'Falsche Antwort', incompleteAnswer: 'Unvollständige Antwort', hallucinatedResponse: 'Erfundene Information', irrelevantAnswer: 'Unpassende Antwort', other: 'Sonstiges', additionalComments: 'Zusätzliche Kommentare', commentsPlaceholder: 'Weitere Angaben (optional)', cancel: 'Abbrechen', submitFeedback: 'Feedback senden', consentMessage: 'Ich stimme zu, dass meine Nachrichten zur Beantwortung meiner Anfrage verarbeitet werden.', searchChats: 'Chats durchsuchen', searchMessages: 'Nachrichten durchsuchen', activeNow: 'Jetzt aktiv', online: 'online', businessAccount: 'Geschäftskonto', professionalAccount: 'Professionelles Konto', aiAssistant: 'KI-Kundenassistent', incomingMessage: 'Eingehende Nachricht', responseDelivered: 'Antwort zugestellt', livePreview: 'Live-Vorschau',
  },
  Arabic: {
    copyConversation: 'نسخ المحادثة', conversationCopied: 'تم نسخ المحادثة',
    openChat: 'فتح الدردشة مع', message: 'رسالة', sessionError: 'تعذر بدء محادثة جديدة.', responseError: 'تعذر إكمال هذا الرد.', tryAgain: 'يرجى المحاولة مرة أخرى.', positiveFeedback: 'ملاحظات إيجابية', helpful: 'مفيد', negativeFeedback: 'ملاحظات سلبية', notHelpful: 'غير مفيد', regenerateAnswer: 'إعادة إنشاء الإجابة', regenerate: 'إعادة الإنشاء', feedbackTitle: 'ساعدنا على التحسن', closeFeedback: 'إغلاق الملاحظات', feedbackQuestion: 'ما الخطأ في هذه الإجابة؟', reason: 'السبب', selectReason: 'اختر سببًا', incorrectAnswer: 'إجابة غير صحيحة', incompleteAnswer: 'إجابة غير مكتملة', hallucinatedResponse: 'معلومات مختلقة', irrelevantAnswer: 'إجابة غير ذات صلة', other: 'أخرى', additionalComments: 'تعليقات إضافية', commentsPlaceholder: 'أخبرنا بالمزيد (اختياري)', cancel: 'إلغاء', submitFeedback: 'إرسال الملاحظات', consentMessage: 'أوافق على معالجة رسائلي للرد على طلبي.', searchChats: 'البحث في الدردشات', searchMessages: 'البحث في الرسائل', activeNow: 'نشط الآن', online: 'متصل', businessAccount: 'حساب أعمال', professionalAccount: 'حساب احترافي', aiAssistant: 'مساعد عملاء بالذكاء الاصطناعي', incomingMessage: 'رسالة واردة', responseDelivered: 'تم إرسال الرد', livePreview: 'معاينة مباشرة',
  },
};

export function getWidgetLocale(language?: string): WidgetLocale {
  return locales[language ?? 'English'] ?? locales.English!;
}

export function getChatUiLocale(language?: string): ChatUiLocale {
  return chatUiLocales[language ?? 'English'] ?? chatUiLocales.English!;
}

export function localizeAgentAppearance(appearance: AgentAppearance, language: string): AgentAppearance {
  const locale = getWidgetLocale(language);
  const chatUi = getChatUiLocale(language);
  return {
    ...appearance,
    interfaceLanguage: language,
    textDirection: language === 'Arabic' ? 'rtl' : 'ltr',
    welcomeTitle: locale.welcomeTitle,
    welcomeMessage: locale.welcomeMessage,
    placeholder: locale.placeholder,
    suggestedQuestions: [...locale.suggestedQuestions],
    translations: { ...locale.translations },
    consentMessage: chatUi.consentMessage,
  };
}
