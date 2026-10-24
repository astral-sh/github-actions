const path = require("node:path");
const run = require("../python.cjs");

module.exports = function (operation, configuration) {
  return run([path.join(__dirname, "cache.py"), operation, configuration]);
};
