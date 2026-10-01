import { describe, expect, it } from 'vitest';
import {
  StudentImportParseError,
  parseStudentImportText,
} from '@/lib/education-student-import-api';

describe('parseStudentImportText', () => {
  it('parses quoted CSV fields and import provisioning columns', () => {
    const rows = parseStudentImportText([
      'student_id,name,email,identity_type,identifier,identity_verified,course_code,batch_code,agent_id,enrollment_status,starts_on,ends_on,custom_fields',
      'student-001,"Asha, Verma",Asha@Example.com,whatsapp,+919876543210,yes,cpa,cpa-2026-a,agt_123,active,2026-09-01,2027-06-30,"{""language"":""en"",""level"":2}"',
    ].join('\n'));

    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({
      studentNumber: 'student-001',
      name: 'Asha, Verma',
      email: 'Asha@Example.com',
      identityType: 'whatsapp',
      identifier: '+919876543210',
      identityVerified: true,
      courseCode: 'cpa',
      batchCode: 'cpa-2026-a',
      agentPublicId: 'agt_123',
      enrollmentStatus: 'active',
      startsOn: '2026-09-01',
      endsOn: '2027-06-30',
      customFields: { language: 'en', level: 2 },
    });
  });

  it('accepts tab-delimited rows copied from Excel or Google Sheets', () => {
    const rows = parseStudentImportText([
      'student_id\tname\temail\tidentity_type\tidentifier',
      'STUDENT-002\tRavi Kumar\travi@example.com\ttelegram\t123456789',
    ].join('\n'));

    expect(rows[0]?.studentNumber).toBe('STUDENT-002');
    expect(rows[0]?.identityType).toBe('telegram');
    expect(rows[0]?.identifier).toBe('123456789');
  });

  it('rejects unknown or incomplete headers before calling the API', () => {
    expect(() => parseStudentImportText('student_id,unknown_column\nS-1,value')).toThrow(StudentImportParseError);
    try {
      parseStudentImportText('student_id,unknown_column\nS-1,value');
    } catch (reason) {
      expect(reason).toBeInstanceOf(StudentImportParseError);
      expect((reason as StudentImportParseError).problems.join(' ')).toMatch(/missing required name column/i);
      expect((reason as StudentImportParseError).problems.join(' ')).toMatch(/unknown columns/i);
    }
  });

  it('enforces the same 500-row cap as the backend', () => {
    const lines = ['student_id,name'];
    for (let index = 0; index < 501; index += 1) lines.push(`S-${index},Student ${index}`);
    expect(() => parseStudentImportText(lines.join('\n'))).toThrow(/maximum is 500/i);
  });
});
