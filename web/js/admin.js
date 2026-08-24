// LabBot - 관리자 화면 스크립트 (Supabase items 테이블 연동)
// TODO: 파손 신고 목록은 Supabase 연동 후 실제 데이터로 렌더링할 것

document.addEventListener("DOMContentLoaded", async () => {
  const gate = document.getElementById("adminGate");
  const panel = document.getElementById("adminPanel");
  const loginForm = document.getElementById("adminLoginForm");
  const loginError = document.getElementById("adminLoginError");
  const logoutBtn = document.getElementById("adminLogoutBtn");

  const tabButtons = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  const addForm = document.getElementById("itemAddForm");
  const categorySelect = document.getElementById("newItemCategory");
  const stockTableBody = document.getElementById("stockTableBody");
  const historyTableBody = document.getElementById("historyTableBody");

  function renderCategoryOptions() {
    categorySelect.innerHTML = LAB_CATEGORIES.filter((c) => c.key !== "all")
      .map((c) => `<option value="${c.key}">${c.label}</option>`)
      .join("");
  }

  async function loadAllItems() {
    return window.LabBotItems.searchItems({});
  }

  async function renderStockTable() {
    let items;
    try {
      items = await loadAllItems();
    } catch (err) {
      alert("물품 목록을 불러오지 못했습니다: " + (err.message || err));
      return;
    }

    stockTableBody.innerHTML = "";

    items.forEach((item) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${item.name}</td>
        <td>${item.categoryLabel}</td>
        <td>${item.location}</td>
        <td class="mono">${item.qr_code}</td>
        <td><input type="number" class="stock-input" min="0" value="${item.available_qty}" data-field="available" /></td>
        <td><input type="number" class="stock-input" min="0" value="${item.total_qty}" data-field="total" /></td>
        <td class="stock-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="save">저장</button>
          <button type="button" class="btn btn-danger btn-sm" data-action="delete">삭제</button>
        </td>
      `;

      row.querySelector('[data-action="save"]').addEventListener("click", async (e) => {
        const button = e.currentTarget;
        const availableInput = row.querySelector('[data-field="available"]');
        const totalInput = row.querySelector('[data-field="total"]');

        const available_qty = Number(availableInput.value);
        const total_qty = Number(totalInput.value);

        if (
          !Number.isFinite(available_qty) ||
          !Number.isFinite(total_qty) ||
          available_qty < 0 ||
          total_qty < 0
        ) {
          alert("재고 수량은 0 이상의 숫자여야 합니다.");
          return;
        }

        if (available_qty > total_qty) {
          alert("대여가능 수량은 총 수량을 넘을 수 없습니다.");
          return;
        }

        button.disabled = true;
        try {
          await window.LabBotItems.updateItemStock(item.id, { available_qty, total_qty });
        } catch (err) {
          alert(err.message || "재고 수정에 실패했습니다.");
        } finally {
          button.disabled = false;
        }
        await renderStockTable();
      });

      row.querySelector('[data-action="delete"]').addEventListener("click", async () => {
        if (!confirm(`"${item.name}"을(를) 삭제하시겠습니까?`)) return;

        try {
          await window.LabBotItems.deleteItem(item.id);
          await renderStockTable();
        } catch (err) {
          alert(err.message || "삭제에 실패했습니다.");
        }
      });

      stockTableBody.appendChild(row);
    });
  }

  function renderHistoryTable() {
    const rentals = window.LabBotRentals.loadRentals();
    const rows = [];

    rentals.forEach((r) => {
      rows.push({ user: r.userName, item: r.itemName, type: "대여", time: r.rentedAt });
      if (r.returnedAt) {
        rows.push({ user: r.userName, item: r.itemName, type: "반납", time: r.returnedAt });
      }
    });

    rows.sort((a, b) => new Date(b.time) - new Date(a.time));

    historyTableBody.innerHTML = rows
      .map(
        (row) => `
        <tr>
          <td>${row.user}</td>
          <td>${row.item}</td>
          <td><span class="badge badge-${row.type === "대여" ? "inuse" : "available"}"><span class="badge-dot"></span>${row.type}</span></td>
          <td>${new Date(row.time).toLocaleString("ko-KR")}</td>
        </tr>
      `
      )
      .join("");
  }

  addForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const name = document.getElementById("newItemName").value.trim();
    const category = categorySelect.value;
    const location = document.getElementById("newItemLocation").value.trim();
    const total_qty = Number(document.getElementById("newItemTotal").value);

    if (!name || !location || !Number.isFinite(total_qty) || total_qty < 1) {
      alert("모든 항목을 올바르게 입력해주세요.");
      return;
    }

    const submitBtn = addForm.querySelector('button[type="submit"]');
    submitBtn.disabled = true;

    try {
      await window.LabBotItems.createItem({ name, category, location, total_qty });
      addForm.reset();
      await renderStockTable();
    } catch (err) {
      alert("물품 등록에 실패했습니다: " + (err.message || err));
    } finally {
      submitBtn.disabled = false;
    }
  });

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;

      tabButtons.forEach((b) => b.classList.remove("active"));
      tabPanels.forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById(`tab-${target}`).classList.add("active");
    });
  });

  async function showPanel() {
    gate.style.display = "none";
    panel.style.display = "block";
    renderCategoryOptions();
    await renderStockTable();
    renderHistoryTable();
  }

  function showGate() {
    gate.style.display = "block";
    panel.style.display = "none";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.style.display = "none";

    const email = document.getElementById("adminEmail").value.trim();
    const password = document.getElementById("adminPassword").value;

    try {
      await window.LabBotAuth.signIn({ email, password });
    } catch (err) {
      loginError.textContent = "관리자 계정 정보가 올바르지 않습니다.";
      loginError.style.display = "block";
      return;
    }

    const session = await window.LabBotAuth.getSession();
    if (!session || session.role !== "admin") {
      await window.LabBotAuth.signOut();
      loginError.textContent = "관리자 계정 정보가 올바르지 않습니다.";
      loginError.style.display = "block";
      return;
    }

    await showPanel();
  });

  logoutBtn.addEventListener("click", async () => {
    await window.LabBotAuth.signOut();
    if (window.LabBotNav) {
      window.LabBotNav.goTo("index.html");
    } else {
      window.location.href = "index.html";
    }
  });

  const session = await window.LabBotAuth.getSession();
  if (session && session.role === "admin") {
    await showPanel();
  } else {
    showGate();
  }
});
