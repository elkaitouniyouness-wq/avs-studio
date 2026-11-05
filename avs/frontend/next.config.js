/** L'API est jointe via un rewrite même origine (cookies httpOnly). En production, un reverse proxy (Caddy) route /api directement vers FastAPI. */
const API = process.env.API_URL || "http://localhost:8000";
module.exports = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};
