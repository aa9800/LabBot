// LabBot - 대여/반납 기록 공통 스크립트
// TODO: Supabase 대여 이력 테이블 연동 후 아래 localStorage 기반 로직을 교체할 것
// 마이페이지, 물품목록, 관리자 화면에서 공통으로 사용 (window.LabBotRentals 제공)

const LABBOT_RENTALS_KEY = "labbot_rentals";

function loadRentals() {
  try {
    return JSON.parse(localStorage.getItem(LABBOT_RENTALS_KEY)) || [];
  } catch (e) {
    return [];
  }
}

function saveRentals(rentals) {
  localStorage.setItem(LABBOT_RENTALS_KEY, JSON.stringify(rentals));
}

// 사용자가 물품을 대여할 때 기록을 추가
function addRentalRecord(item, user) {
  const rentals = loadRentals();
  rentals.unshift({
    id: `rental-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    itemId: item.id,
    itemName: item.name,
    category: item.categoryLabel,
    location: item.location,
    userEmail: user.email,
    userName: user.name,
    rentedAt: new Date().toISOString(),
    returnedAt: null,
    status: "rented",
  });
  saveRentals(rentals);
}

// 반납 시 해당 물품의 가장 오래된 미반납 기록을 반납 처리 (선입선출)
function returnRentalRecord(itemId) {
  const rentals = loadRentals();
  const target = rentals
    .filter((r) => r.itemId === itemId && r.status === "rented")
    .sort((a, b) => new Date(a.rentedAt) - new Date(b.rentedAt))[0];

  if (target) {
    target.status = "returned";
    target.returnedAt = new Date().toISOString();
    saveRentals(rentals);
  }
}

function getRentalsByUser(email) {
  return loadRentals().filter((r) => r.userEmail === email);
}

window.LabBotRentals = {
  loadRentals,
  addRentalRecord,
  returnRentalRecord,
  getRentalsByUser,
};
