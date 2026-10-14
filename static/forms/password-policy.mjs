/** Checks displayed beside the signup password; login accepts legacy passwords. */
// Python str.isdigit() includes decimal digits and these Unicode Digit ranges.
// Numeric characters such as fractions and Roman numerals do not qualify.
const DIGIT = /[\p{Nd}\u{b2}-\u{b3}\u{b9}\u{1369}-\u{1371}\u{19da}\u{2070}\u{2074}-\u{2079}\u{2080}-\u{2089}\u{2460}-\u{2468}\u{2474}-\u{247c}\u{2488}-\u{2490}\u{24ea}\u{24f5}-\u{24fd}\u{24ff}\u{2776}-\u{277e}\u{2780}-\u{2788}\u{278a}-\u{2792}\u{10a40}-\u{10a43}\u{10e60}-\u{10e68}\u{11052}-\u{1105a}\u{1f100}-\u{1f10a}]/u;

export function passwordChecks(value) {
    const length = Array.from(value).length;
    return {
        length: length >= 8 && length <= 128,
        case: /\p{Lowercase}/u.test(value) && /\p{Uppercase}/u.test(value),
        number: DIGIT.test(value),
        symbol: /[!@#$%&_*]/.test(value),
    };
}
