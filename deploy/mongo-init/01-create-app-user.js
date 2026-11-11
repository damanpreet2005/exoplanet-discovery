// Runs once, by the official mongo image, the first time the data volume is
// initialised (files in /docker-entrypoint-initdb.d are skipped on every
// later start). Creates the least-privilege account the gateway connects
// with: CRUD + index/collection creation on the application database only --
// no drop, no user/role administration, no access to any other database.
//
// Credentials come from the container environment (see docker-compose.yml
// and .env.example); nothing secret is written in this file.
const appDbName = process.env.MONGO_APP_DB || "exodiscovery";
const appUser = process.env.MONGO_APP_USERNAME;
const appPassword = process.env.MONGO_APP_PASSWORD;

if (!appUser || !appPassword) {
  throw new Error("MONGO_APP_USERNAME and MONGO_APP_PASSWORD must be set.");
}

const appDb = db.getSiblingDB(appDbName);

appDb.createRole({
  role: "exodiscoveryApp",
  privileges: [
    {
      resource: { db: appDbName, collection: "" },
      actions: ["find", "insert", "update", "remove", "createIndex", "createCollection", "listCollections", "listIndexes"],
    },
  ],
  roles: [],
});

appDb.createUser({
  user: appUser,
  pwd: appPassword,
  roles: [{ role: "exodiscoveryApp", db: appDbName }],
});
