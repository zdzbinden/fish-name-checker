/**
 * Shared test bootstrap — loads fish_names.json and initializes the engine.
 * Usage: const { engine, lookups, db } = require('./setup');
 */
const fs = require('fs');
const path = require('path');
const engine = require('../js/engine.js');

const raw = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'data', 'fish_names.json'), 'utf-8')
);
const lookups = engine.buildLookups(raw);

module.exports = { engine, lookups, db: raw };
