import test from 'node:test';
import assert from 'node:assert/strict';
import { passwordChecks } from '../static/forms/password-policy.mjs';

test('a password with all required characters satisfies the checklist', () => {
    assert.deepEqual(passwordChecks('Password1!'), {length:true, case:true, number:true, symbol:true});
    assert.equal(passwordChecks('Password1').symbol, false);
    assert.equal(passwordChecks('pass1!').length, false);
});

test('Roman numerals and fractions do not satisfy the server digit requirement', () => {
    assert.equal(passwordChecks('AbcdefⅧ!').number, false);
    assert.equal(passwordChecks('Abcdef½!').number, false);
});

test('decimal and superscript digits accepted by the server satisfy the checklist', () => {
    for (const digit of ['0', '٣', '²', '⑨']) assert.equal(passwordChecks(`Abcdef${digit}!`).number, true);
});

test('Unicode casing and code point length follow the server rules', () => {
    assert.equal(passwordChecks('Aª12345!').case, true);
    assert.equal(passwordChecks('Ab1!😀😀😀').length, false);
    assert.equal(passwordChecks('Ab1!😀😀😀😀').length, true);
    assert.equal(passwordChecks('A1!' + 'a'.repeat(126)).length, false);
});
