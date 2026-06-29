// Stub — auth container only handles authentication, not AI writing
async function processSession() { throw new Error('Not available in auth service'); }
async function processImitation() { throw new Error('Not available in auth service'); }
async function processImitationFree() { throw new Error('Not available in auth service'); }
async function processEnhancedImitation() { throw new Error('Not available in auth service'); }
function countTextLength() { return 0; }
async function refundCreditOnce() {}

module.exports = { processSession, processImitation, processImitationFree, processEnhancedImitation, countTextLength, refundCreditOnce };
