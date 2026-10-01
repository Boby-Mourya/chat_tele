import type { AgentPurpose } from '@/types';

export type TemplateButton = { type: 'quick_reply' | 'url' | 'phone'; text: string; value?: string };

export type WhatsAppTemplateDraft = {
  id: string;
  purpose: AgentPurpose;
  name: string;
  category: 'UTILITY' | 'MARKETING';
  occasion: string;
  header: string;
  body: string;
  footer: string;
  buttons: TemplateButton[];
};

const template = (
  purpose: AgentPurpose,
  id: string,
  name: string,
  category: WhatsAppTemplateDraft['category'],
  occasion: string,
  header: string,
  body: string,
  footer: string,
  buttons: TemplateButton[],
): WhatsAppTemplateDraft => ({ purpose, id, name, category, occasion, header, body, footer, buttons });

export const whatsappTemplateLibrary: WhatsAppTemplateDraft[] = [
  template('education', 'edu-welcome', 'student_course_welcome', 'UTILITY', 'Enrollment', 'Welcome to {{1}} 🎓', 'Hi {{2}}, your enrollment in *{{1}}* is confirmed.\n\nBatch: {{3}}\nStarts: {{4}}\nStudent ID: {{5}}\n\nYour learning journey begins here. We are delighted to have you with us!', 'Reply HELP whenever you need us.', [{ type: 'url', text: 'Open student portal', value: 'https://example.com/portal/{{1}}' }, { type: 'quick_reply', text: 'View schedule' }]),
  template('education', 'edu-class', 'class_reminder', 'UTILITY', 'Class reminder', 'Your class starts soon ⏰', 'Hi {{1}}, a reminder that *{{2}}* begins at {{3}} on {{4}}.\n\nTopic: {{5}}\nFaculty: {{6}}\n\nKeep your notebook ready and join a few minutes early.', 'Keep learning. Keep growing.', [{ type: 'url', text: 'Join class', value: 'https://example.com/class/{{1}}' }, { type: 'quick_reply', text: 'Need help' }]),
  template('education', 'edu-plan', 'weekly_study_plan', 'UTILITY', 'Study plan', 'Your weekly learning plan ✨', 'Hello {{1}}, here is your plan for *{{2}}*:\n\n✅ {{3}}\n📖 {{4}}\n📝 {{5}}\n🎯 Weekly goal: {{6}}\n\nSmall, consistent steps create exceptional results.', 'You have got this!', [{ type: 'url', text: 'Start learning', value: 'https://example.com/learn' }, { type: 'quick_reply', text: 'Ask a question' }]),
  template('education', 'edu-result', 'assessment_result', 'UTILITY', 'Results', 'Your result is ready 🏆', 'Hi {{1}}, your result for *{{2}}* is now available.\n\nScore: *{{3}}*\nResult: {{4}}\nInstructor note: {{5}}\n\nReview your feedback and keep moving forward.', 'Every attempt is progress.', [{ type: 'url', text: 'View result', value: 'https://example.com/results/{{1}}' }, { type: 'quick_reply', text: 'Talk to faculty' }]),
  template('education', 'edu-fee', 'fee_payment_reminder', 'UTILITY', 'Fee reminder', 'Fee reminder for {{1}}', 'Hi {{2}}, this is a friendly reminder that {{3}} for *{{1}}* is due on {{4}}.\n\nAmount: {{5}}\nReference: {{6}}\n\nIf you have already paid, please ignore this message.', 'Secure payments only through the official portal.', [{ type: 'url', text: 'Pay securely', value: 'https://example.com/pay/{{1}}' }, { type: 'quick_reply', text: 'Payment support' }]),
  template('education', 'edu-material', 'new_learning_material', 'UTILITY', 'Learning material', 'New study material available 📚', 'Hi {{1}}, we have added *{{2}}* to your {{3}} course.\n\nIncludes: {{4}}\nRecommended by: {{5}}\n\nSave it now and continue learning at your pace.', 'Available in your course library.', [{ type: 'url', text: 'View material', value: 'https://example.com/material/{{1}}' }]),
  template('education', 'edu-doubt', 'doubt_session_invite', 'UTILITY', 'Doubt session', 'Live doubt-clearing session 💬', 'Hi {{1}}, join our live doubt session for *{{2}}*.\n\nDate: {{3}}\nTime: {{4}}\nFaculty: {{5}}\n\nBring your questions—we will solve them together.', 'Seats may be limited.', [{ type: 'quick_reply', text: 'I will attend' }, { type: 'quick_reply', text: 'Cannot attend' }]),
  template('education', 'edu-progress', 'learning_progress_nudge', 'MARKETING', 'Engagement', 'You are closer than you think 🌟', 'Hi {{1}}, you have completed *{{2}}%* of {{3}}. Just {{4}} lessons remain in this milestone.\n\nContinue where you stopped and keep your momentum alive.', 'Progress looks good on you.', [{ type: 'url', text: 'Continue learning', value: 'https://example.com/continue' }]),

  template('support', 'support-ticket', 'support_ticket_created', 'UTILITY', 'Ticket created', 'We are on it 🛠️', 'Hi {{1}}, your support request has been recorded.\n\nTicket: *{{2}}*\nIssue: {{3}}\nPriority: {{4}}\nExpected update: {{5}}\n\nOur team will keep you informed here.', 'Please keep your ticket number handy.', [{ type: 'url', text: 'Track request', value: 'https://example.com/support/{{1}}' }, { type: 'quick_reply', text: 'Add details' }]),
  template('support', 'support-update', 'support_case_update', 'UTILITY', 'Case update', 'Update on ticket {{1}}', 'Hello {{2}}, there is a new update on your request:\n\n*{{3}}*\n\nCurrent status: {{4}}\nNext update by: {{5}}', 'We appreciate your patience.', [{ type: 'quick_reply', text: 'Issue resolved' }, { type: 'quick_reply', text: 'Still need help' }]),
  template('support', 'support-resolution', 'support_resolution_check', 'UTILITY', 'Resolution check', 'Is everything working now? ✅', 'Hi {{1}}, we completed the requested action for ticket *{{2}}*.\n\nResolution: {{3}}\n\nPlease let us know whether everything is working as expected.', 'Your feedback helps us serve you better.', [{ type: 'quick_reply', text: 'Yes, resolved' }, { type: 'quick_reply', text: 'No, reopen' }]),
  template('support', 'support-agent', 'support_agent_callback', 'UTILITY', 'Callback', 'Your callback is scheduled 📞', 'Hi {{1}}, {{2}} from our support team will call you on {{3}} between {{4}} and {{5}} regarding ticket {{6}}.', 'Need another time? Reply below.', [{ type: 'quick_reply', text: 'Time works' }, { type: 'quick_reply', text: 'Reschedule' }]),
  template('support', 'support-outage', 'service_status_update', 'UTILITY', 'Service alert', 'Service status update', 'Hello {{1}}, we are currently investigating {{2}} affecting {{3}}.\n\nStarted: {{4}}\nCurrent status: {{5}}\nNext update: {{6}}\n\nWe are sorry for the disruption.', 'Follow the live status for updates.', [{ type: 'url', text: 'View live status', value: 'https://status.example.com' }]),
  template('support', 'support-guide', 'support_how_to_guide', 'UTILITY', 'Help guide', 'A quick guide for {{1}} 💡', 'Hi {{2}}, follow these steps:\n\n1. {{3}}\n2. {{4}}\n3. {{5}}\n\nIf the issue continues, reply and a specialist will assist you.', 'Never share passwords or OTPs.', [{ type: 'url', text: 'Open visual guide', value: 'https://example.com/help/{{1}}' }, { type: 'quick_reply', text: 'Contact specialist' }]),
  template('support', 'support-feedback', 'support_feedback_request', 'UTILITY', 'Feedback', 'How did we do?', 'Hi {{1}}, ticket {{2}} was recently resolved by {{3}}. How would you rate your support experience?', 'Your feedback takes less than a minute.', [{ type: 'quick_reply', text: 'Excellent' }, { type: 'quick_reply', text: 'Good' }, { type: 'quick_reply', text: 'Needs improvement' }]),
  template('support', 'support-renewal', 'service_renewal_notice', 'UTILITY', 'Renewal', 'Your service renews soon', 'Hi {{1}}, your *{{2}}* plan is scheduled to renew on {{3}}.\n\nPlan: {{4}}\nAmount: {{5}}\n\nReview your billing details before renewal.', 'Manage your plan securely online.', [{ type: 'url', text: 'Manage plan', value: 'https://example.com/billing' }, { type: 'quick_reply', text: 'Billing help' }]),

  template('lead_generation', 'lead-welcome', 'lead_welcome', 'MARKETING', 'New enquiry', 'Thanks for your interest, {{1}} 👋', 'You are exploring *{{2}}*—a great choice. I can help with fees, outcomes, eligibility, and the best next step for your goals.\n\nWhat would you like to discover first?', 'Reply STOP to opt out.', [{ type: 'quick_reply', text: 'View fees' }, { type: 'quick_reply', text: 'Course details' }, { type: 'quick_reply', text: 'Talk to advisor' }]),
  template('lead_generation', 'lead-brochure', 'course_brochure_followup', 'MARKETING', 'Brochure follow-up', 'Your {{1}} guide is ready 📘', 'Hi {{2}}, here is the detailed guide you requested for *{{1}}*.\n\nInside you will find:\n✓ Curriculum\n✓ Career outcomes\n✓ Fees and plans\n✓ Upcoming batches\n\nWould you like help choosing the right batch?', 'Reply STOP to opt out.', [{ type: 'url', text: 'View brochure', value: 'https://example.com/brochure/{{1}}' }, { type: 'quick_reply', text: 'Speak to advisor' }]),
  template('lead_generation', 'lead-counselling', 'counselling_session_invite', 'MARKETING', 'Counselling', 'Your goals deserve a clear plan 🎯', 'Hi {{1}}, reserve a complimentary {{2}}-minute counselling session with {{3}}. We will map the right path based on your background, timeline, and career goals.', 'No obligation—just useful guidance.', [{ type: 'url', text: 'Book my session', value: 'https://example.com/book/{{1}}' }, { type: 'quick_reply', text: 'Share time options' }]),
  template('lead_generation', 'lead-event', 'webinar_invitation', 'MARKETING', 'Event invitation', 'You are invited: {{1}} 🎙️', 'Join {{2}} on {{3}} at {{4}} for a practical session on *{{1}}*.\n\nYou will learn:\n• {{5}}\n• {{6}}\n• {{7}}\n\nSave your complimentary seat today.', 'Reply STOP to opt out.', [{ type: 'url', text: 'Reserve my seat', value: 'https://example.com/event/{{1}}' }, { type: 'quick_reply', text: 'Send recording' }]),
  template('lead_generation', 'lead-offer', 'personalised_admission_offer', 'MARKETING', 'Offer', 'A special opportunity for {{1}} ✨', 'Hi {{2}}, based on your interest in *{{3}}*, you are eligible for {{4}} until {{5}}.\n\nBenefit: {{6}}\nNext batch: {{7}}\n\nWould you like an advisor to explain the details?', 'Terms apply. Reply STOP to opt out.', [{ type: 'url', text: 'View offer', value: 'https://example.com/offer/{{1}}' }, { type: 'quick_reply', text: 'Call me' }]),
  template('lead_generation', 'lead-deadline', 'admission_deadline_reminder', 'MARKETING', 'Deadline', 'Applications close {{1}} ⏳', 'Hi {{2}}, admissions for *{{3}}* close on {{1}}. Your application is {{4}}.\n\nComplete the remaining step to be considered for the {{5}} batch.', 'Reply STOP to opt out.', [{ type: 'url', text: 'Complete application', value: 'https://example.com/apply/{{1}}' }, { type: 'quick_reply', text: 'I need help' }]),
  template('lead_generation', 'lead-success', 'student_success_story', 'MARKETING', 'Social proof', 'A journey you may relate to 🌟', '{{1}} started with the same goal as you: {{2}}. After completing *{{3}}*, they achieved {{4}}.\n\nExplore their story and see what your own path could look like.', 'Results vary by learner. Reply STOP to opt out.', [{ type: 'url', text: 'Read the story', value: 'https://example.com/story/{{1}}' }, { type: 'quick_reply', text: 'Explore program' }]),
  template('lead_generation', 'lead-reengage', 'lead_reengagement', 'MARKETING', 'Re-engagement', 'Still considering {{1}}?', 'Hi {{2}}, choosing the right program takes time. Since you last explored *{{1}}*, we have added {{3}}.\n\nWould a concise comparison or a quick conversation help?', 'Reply STOP to opt out.', [{ type: 'quick_reply', text: 'Send comparison' }, { type: 'quick_reply', text: 'Talk to advisor' }, { type: 'quick_reply', text: 'Not interested' }]),
];

export const purposeTemplateLabels: Record<AgentPurpose, string> = {
  education: 'Education',
  support: 'Support',
  lead_generation: 'Lead generation',
};
