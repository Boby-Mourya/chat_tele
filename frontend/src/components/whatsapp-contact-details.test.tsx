import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { WhatsAppContactDetails } from './whatsapp-contact-details';

afterEach(cleanup);
it('displays actual WhatsApp sender data, including a dialable international number', () => {
  render(<WhatsAppContactDetails contact={{ phoneNumber: '+919876543210', waId: '919876543210', profileName: 'Anan', lastMessageAt: '2026-09-15T11:20:00Z', lastMessageType: 'text' }} />);
  expect(screen.getByRole('link', { name: '+919876543210' })).toHaveAttribute('href', 'tel:+919876543210');
  expect(screen.getByText('Anan')).toBeInTheDocument();
  expect(screen.getByText('919876543210')).toBeInTheDocument();
  expect(screen.getByText('Last incoming message')).toBeInTheDocument();
});
it('does not invent missing profile information', () => {
  const { rerender } = render(<WhatsAppContactDetails contact={{ phoneNumber: '+919876543210', waId: '919876543210' }} />);
  expect(screen.getByText('Not shared')).toBeInTheDocument();
  expect(screen.queryByText('Last incoming message')).not.toBeInTheDocument();
  rerender(<WhatsAppContactDetails contact={null} />);
  expect(screen.queryByRole('region')).not.toBeInTheDocument();
});
