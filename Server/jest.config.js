/** Jest 設定：先載入 .env.test（override），再載入任何模組。 */
module.exports = {
  testEnvironment: 'node',
  setupFiles: ['<rootDir>/tests/setup-env.js'],
  testMatch: ['<rootDir>/tests/**/*.test.js'],
  testTimeout: 30000,
  collectCoverageFrom: ['lib/**/*.js', 'routes/**/*.js', 'app.js'],
  coveragePathIgnorePatterns: ['/node_modules/'],
}
