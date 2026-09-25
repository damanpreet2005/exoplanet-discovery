const express = require("express");
const mlClient = require("../services/mlClient");

const router = express.Router();

// Proxies the ML service's feature display metadata so the frontend never
// calls the ML service directly.
router.get("/feature-schema", async (req, res, next) => {
  try {
    const schema = await mlClient.fetchFeatureSchema();
    return res.status(200).json(schema);
  } catch (err) {
    return next(err);
  }
});

module.exports = router;
