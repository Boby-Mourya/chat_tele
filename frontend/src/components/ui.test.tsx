import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it } from 'vitest';
import { Field } from './ui';

afterEach(cleanup);

it('associates shared field labels, hints and errors with native controls', async () => {
  const { rerender } = render(<Field label="Subject" hint="A short summary"><input /></Field>);
  const input = screen.getByRole('textbox', { name: 'Subject' });
  expect(input).toHaveAccessibleDescription('A short summary');
  await userEvent.click(screen.getByText('Subject'));
  expect(input).toHaveFocus();
  rerender(<Field label="Subject" error="Enter a subject"><input /></Field>);
  expect(input).toHaveAttribute('aria-invalid', 'true');
  expect(input).toHaveAccessibleDescription('Enter a subject');
});

it('preserves explicit identifiers and existing descriptions', () => {
  render(<><p id="external">Required for support</p><Field label="Category" hint="Choose one"><select id="category" aria-describedby="external"><option>General</option></select></Field></>);
  const select = screen.getByRole('combobox', { name: 'Category' });
  expect(select).toHaveAttribute('id', 'category');
  expect(select).toHaveAccessibleDescription('Required for support Choose one');
});
