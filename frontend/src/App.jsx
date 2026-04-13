import React, { useEffect, useMemo, useState } from "react";
import "./App.css";
import {
  Search,
  ShieldCheck,
  ShieldX,
  AlertTriangle,
  HelpCircle,
  Clock3,
  ExternalLink,
} from "lucide-react";

function formatDate(dateString) {
  return dateString ? new Date(dateString).toLocaleString() : "Unknown date";
}

function verdictClass(verdict) {
  switch (verdict) {
    case "True":
      return "badge true";
    case "False":
      return "badge false";
    case "Misleading":
      return "badge misleading";
    case "Uncertain":
      return "badge uncertain";
    default:
      return "badge";
  }
}

function verdictIcon(verdict) {
  switch (verdict) {
    case "True":
      return <ShieldCheck size={16} />;
    case "False":
      return <ShieldX size={16} />;
    case "Misleading":
      return <AlertTriangle size={16} />;
    case "Uncertain":
      return <HelpCircle size={16} />;
    default:
      return <HelpCircle size={16} />;
  }
}

function GoogleLoginBox({ user, setUser }) {
  useEffect(() => {
    if (user) return;

    const existingScript = document.querySelector(
      'script[src="https://accounts.google.com/gsi/client"]'
    );

    const initializeGoogle = () => {
      if (!window.google) return;

      window.google.accounts.id.initialize({
        client_id: import.meta.env.VITE_GOOGLE_CLIENT_ID,
        callback: handleCredentialResponse,
      });

      const el = document.getElementById("googleSignInDiv");
      if (el) {
        el.innerHTML = "";
        window.google.accounts.id.renderButton(el, {
          theme: "outline",
          size: "large",
          shape: "pill",
          text: "signin_with",
        });
      }
    };

    if (existingScript) {
      initializeGoogle();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = initializeGoogle;
    document.body.appendChild(script);
  }, [user]);

  async function handleCredentialResponse(response) {
    try {
      const res = await fetch("http://127.0.0.1:5000/auth/google", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          credential: response.credential,
        }),
      });

      const data = await res.json();

      if (data.success) {
        setUser(data.user);
      } else {
        alert(data.error || "Google login failed");
      }
    } catch (err) {
      alert("Google login failed");
      console.error(err);
    }
  }

  async function handleLogout() {
    await fetch("http://127.0.0.1:5000/logout", {
      method: "POST",
      credentials: "include",
    });
    setUser(null);
    window.location.reload();
  }

  if (user) {
    return (
      <div className="user-box">
        {user.picture_url ? (
          <img className="user-avatar" src={user.picture_url} alt={user.name} />
        ) : null}
        <div>
          <div className="user-name">{user.name}</div>
          <div className="user-email">{user.email}</div>
        </div>
        <button className="logout-btn" onClick={handleLogout}>
          Logout
        </button>
      </div>
    );
  }

  return <div id="googleSignInDiv"></div>;
}

export default function App() {
  const [checks, setChecks] = useState([]);
  const [selectedCheck, setSelectedCheck] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");
  const [verdictFilter, setVerdictFilter] = useState("All");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [user, setUser] = useState(null);

  useEffect(() => {
    async function loadMe() {
      try {
        const res = await fetch("http://127.0.0.1:5000/me", {
          credentials: "include",
        });

        if (!res.ok) return;

        const data = await res.json();
        if (data.logged_in) {
          setUser(data.user);
        }
      } catch (err) {
        console.error(err);
      }
    }

    loadMe();
  }, []);

  useEffect(() => {
    async function loadChecks() {
      try {
        setLoading(true);
        setError("");

        const res = await fetch("http://127.0.0.1:5000/fact-checks", {
          credentials: "include",
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();

        setChecks(Array.isArray(data) ? data : []);
        setError("");

        if (Array.isArray(data) && data.length > 0) {
          setSelectedId(data[0].id);
        } else {
          setSelectedId(null);
          setSelectedCheck(null);
        }
      } catch (err) {
        console.error("loadChecks failed:", err);
        setError("Failed to load fact checks.");
      } finally {
        setLoading(false);
      }
    }

    loadChecks();
  }, [user]);

  useEffect(() => {
    if (!selectedId) return;

    async function loadDetail() {
      try {
        setDetailLoading(true);
        setError("");

        const res = await fetch(`http://127.0.0.1:5000/fact-checks/${selectedId}`, {
          credentials: "include",
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        setSelectedCheck(data);
      } catch (err) {
        console.error("loadDetail failed:", err);
        setError("Failed to load fact check details.");
      } finally {
        setDetailLoading(false);
      }
    }

    loadDetail();
  }, [selectedId]);

  const filteredChecks = useMemo(() => {
    return checks.filter((item) => {
      const matchesVerdict =
        verdictFilter === "All" || item.verdict === verdictFilter;

      const q = query.trim().toLowerCase();
      const explanationText = (item.explanation || "").toLowerCase();
      const claimText = (item.claim || "").toLowerCase();
      const verdictText = (item.verdict || "").toLowerCase();

      const matchesSearch =
        !q ||
        claimText.includes(q) ||
        explanationText.includes(q) ||
        verdictText.includes(q);

      return matchesVerdict && matchesSearch;
    });
  }, [checks, query, verdictFilter]);

  return (
    <div className="page">
      <div className="bg-glow glow1"></div>
      <div className="bg-glow glow2"></div>
      <div className="bg-glow glow3"></div>

      <div className="container">
        <header className="hero">
          <div>
            <div className="pill">FactLens Dashboard</div>
            <h1>Verification history</h1>
            <p>Browse old checks, inspect verdicts, and review sources.</p>
          </div>

          <GoogleLoginBox user={user} setUser={setUser} />
        </header>

        {error && <div className="card empty-state">{error}</div>}

        <section className="stats">
          <div className="card stat-card">
            <h3>Total checks</h3>
            <p>{checks.length}</p>
          </div>
          <div className="card stat-card">
            <h3>True verdicts</h3>
            <p>{checks.filter((x) => x.verdict === "True").length}</p>
          </div>
          <div className="card stat-card">
            <h3>False verdicts</h3>
            <p>{checks.filter((x) => x.verdict === "False").length}</p>
          </div>
          <div className="card stat-card">
            <h3>Misleading</h3>
            <p>{checks.filter((x) => x.verdict === "Misleading").length}</p>
          </div>
        </section>

        <section className="main-grid">
          <div className="card left-panel">
            <h2>History</h2>

            <div className="search-box">
              <Search size={18} />
              <input
                type="text"
                placeholder="Search claims, explanations, verdicts..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            <select
              className="filter-select"
              value={verdictFilter}
              onChange={(e) => setVerdictFilter(e.target.value)}
            >
              <option value="All">All verdicts</option>
              <option value="True">True</option>
              <option value="False">False</option>
              <option value="Misleading">Misleading</option>
              <option value="Uncertain">Uncertain</option>
              <option value="Error">Error</option>
            </select>

            <div className="history-list">
              {loading ? (
                <div className="empty-state">Loading...</div>
              ) : filteredChecks.length > 0 ? (
                filteredChecks.map((item) => (
                  <button
                    key={item.id}
                    className={`history-item ${selectedId === item.id ? "active" : ""}`}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <div className={verdictClass(item.verdict)}>
                      {verdictIcon(item.verdict)}
                      <span>{item.verdict}</span>
                    </div>

                    <div className="history-claim">{item.claim}</div>

                    <div className="history-time">
                      <Clock3 size={14} />
                      <span>{formatDate(item.created_at)}</span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="empty-state">No checks found.</div>
              )}
            </div>
          </div>

          <div className="right-panel">
            {detailLoading ? (
              <div className="card empty-big">Loading details...</div>
            ) : selectedCheck ? (
              <>
                <div className="card detail-hero">
                  <div className={verdictClass(selectedCheck.verdict)}>
                    {verdictIcon(selectedCheck.verdict)}
                    <span>{selectedCheck.verdict}</span>
                  </div>

                  <h2>{selectedCheck.claim}</h2>
                  <p className="detail-time">{formatDate(selectedCheck.created_at)}</p>

                  <div className="reason-box">
                    <h3>Explanation</h3>
                    <p>{selectedCheck.explanation || "No explanation available."}</p>
                  </div>
                </div>

                <div className="card">
                  <h2 style={{ padding: "20px 20px 0 20px" }}>Sources</h2>

                  <div className="sources-grid">
                    {selectedCheck.sources && selectedCheck.sources.length > 0 ? (
                      selectedCheck.sources.map((source, index) => (
                        <a
                          key={source.id || source.url || index}
                          className="source-card"
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <div className="source-site">
                            {source.url ? new URL(source.url).hostname : "Source"}
                          </div>
                          <div className="source-title">
                            {source.title || source.url || "Untitled Source"}
                          </div>
                          <div className="source-snippet">
                            {source.url || "No additional source details available."}
                          </div>
                          <div className="source-link">
                            <span>Open source</span>
                            <ExternalLink size={14} />
                          </div>
                        </a>
                      ))
                    ) : (
                      <div className="empty-state">No sources saved.</div>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="card empty-big">No check selected.</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}