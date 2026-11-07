// A patient must be told what has not been proven about the AI, and must never
// be told that it has been approved or that it is accurate.
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import PrivacyPolicy from '@/pages/privacy';
import { AiLimitsNote } from './ai-limits-note';

describe('note on the limits of the AI', () => {
  it('says accuracy is unmeasured, no doctor checks it and no regulator approved it', () => {
    render(<AiLimitsNote />);
    const note = screen.getByTestId('text-ai-limits');
    expect(note).toHaveTextContent(/not yet measured how accurate/);
    expect(note).toHaveTextContent(/no doctor checks/);
    expect(note).toHaveTextContent(/can miss results, even ones your lab marked high or low/);
    expect(note).toHaveTextContent(/not been approved by any medical regulator/);
  });

  it('links to the part of the policy that explains the limits', () => {
    render(<AiLimitsNote />);
    expect(screen.getByRole('link', { name: /limits/ })).toHaveAttribute('href', '/privacy#medical');
  });
});

describe('limits in the privacy policy', () => {
  it('names each limit, including the heart model and Indian patients', () => {
    render(<PrivacyPolicy />);
    const part = document.getElementById('medical');
    expect(part).toHaveTextContent(/not yet measured how often our AI reads a report correctly/);
    expect(part).toHaveTextContent(/doctors have not yet tested/);
    expect(part).toHaveTextContent(/not been tested on Indian people/);
    expect(part).toHaveTextContent(/not been approved by any medical regulator/);
  });

  it('stays marked as a draft until a lawyer has reviewed it', () => {
    render(<PrivacyPolicy />);
    expect(screen.getByText(/Draft - being reviewed before launch/)).toBeInTheDocument();
  });
});
