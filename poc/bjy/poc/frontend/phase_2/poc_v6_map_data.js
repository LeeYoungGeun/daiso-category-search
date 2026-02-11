const mapData = {
    // Floor Metadata
    floors: {
        "B1": {
            id: "B1",
            map: "./images/map_b1.jpg",
            width: 1000,
            height: 1200,
            entrance: { x: 50, y: 15, label: "B1 입구 (Main)" }, // Default
            entrances: {
                "main": { x: 50, y: 15, label: "B1 정문 (Main)", ar_x: 0, ar_y: 0 },
                "sub": { x: 35, y: 95, label: "B1 후문 (Sub)", ar_x: -2, ar_y: 18 } // New Entrance
            },
            transits: {
                "B2": { x: 50, y: 95, label: "To B2 (계단)", ar_x: 0, ar_y: 16 }
            }
        },
        "B2": {
            id: "B2",
            map: "./images/map_b2.jpg",
            width: 1000,
            height: 1200,
            entrance: { x: 25, y: 90, label: "B2 진입 (계단)" },
            entrances: {
                "main": { x: 25, y: 90, label: "B2 진입 (계단)", ar_x: 0, ar_y: 0 }
            },
            transits: {
                "B1": { x: 25, y: 90, label: "To B1 (계단)", ar_x: 0, ar_y: 0 }
            }
        }
    },

    // Shelf Mappings
    shelves: {
        // --- B1 Shelves ---
        "A01": { id: "A01", floor: "B1", section: "Stationery (문구)", x: 20, y: 72, ar_x: -6, ar_y: 10 },
        "A02": { id: "A02", floor: "B1", section: "Stationery", x: 20, y: 80, ar_x: -6, ar_y: 11 },

        "B01": { id: "B01", floor: "B1", section: "Season (시즌)", x: 60, y: 35, ar_x: -3, ar_y: 3 },
        "D01": { id: "D01", floor: "B1", section: "Health (건강기능식품)", x: 60, y: 50, ar_x: -3, ar_y: 6 },
        "E01": { id: "E01", floor: "B1", section: "Character (캐릭터)", x: 60, y: 60, ar_x: -3, ar_y: 8 },
        "G01": { id: "G01", floor: "B1", section: "Party/Kids (파티/유아동)", x: 60, y: 75, ar_x: 0, ar_y: 10 },

        "C01": { id: "C01", floor: "B1", section: "Beauty (화장품)", x: 80, y: 30, ar_x: 6, ar_y: 3 },
        "F01": { id: "F01", floor: "B1", section: "Fashion (패션)", x: 80, y: 60, ar_x: 6, ar_y: 9 },
        "H01": { id: "H01", floor: "B1", section: "Interior (인테리어)", x: 80, y: 75, ar_x: 6, ar_y: 12 },
        "K01": { id: "K01", floor: "B1", section: "Snacks (식품)", x: 85, y: 85, ar_x: 7, ar_y: 14 },

        "I01": { id: "I01", floor: "B1", section: "Packaging (포장)", x: 15, y: 85, ar_x: -7, ar_y: 14 },
        "J01": { id: "J01", floor: "B1", section: "Digital (디지털)", x: 50, y: 85, ar_x: 0, ar_y: 14 },


        // --- B2 Shelves ---
        "BA01": { id: "BA01", floor: "B2", section: "Bath (욕실)", x: 55, y: 20, ar_x: -5, ar_y: 16 },
        "JA01": { id: "JA01", floor: "B2", section: "Japanese (일본수입)", x: 55, y: 35, ar_x: -5, ar_y: 12 },
        "HF01": { id: "HF01", floor: "B2", section: "Home Fabric (홈패브릭)", x: 55, y: 45, ar_x: -5, ar_y: 10 },
        "TO01": { id: "TO01", floor: "B2", section: "Tools (공구)", x: 55, y: 55, ar_x: -5, ar_y: 8 },

        "CL01": { id: "CL01", floor: "B2", section: "Cleaning (청소)", x: 70, y: 20, ar_x: -2, ar_y: 16 },

        "LA01": { id: "LA01", floor: "B2", section: "Laundry (세탁)", x: 90, y: 15, ar_x: 5, ar_y: 18 },
        "GP01": { id: "GP01", floor: "B2", section: "Good Place (득템)", x: 92, y: 25, ar_x: 7, ar_y: 16 },

        "ST01": { id: "ST01", floor: "B2", section: "Storage (수납)", x: 85, y: 40, ar_x: 6, ar_y: 13 },
        "NC01": { id: "NC01", floor: "B2", section: "Natural (내추럴)", x: 85, y: 55, ar_x: 6, ar_y: 10 },

        "SP01": { id: "SP01", floor: "B2", section: "Sports (스포츠)", x: 15, y: 72, ar_x: -6, ar_y: 4 },

        "KI01": { id: "KI01", floor: "B2", section: "Kitchen (주방)", x: 80, y: 60, ar_x: 6, ar_y: 4 },

        "PE01": { id: "PE01", floor: "B2", section: "Pets (반려동물)", x: 30, y: 70, ar_x: -3, ar_y: 4 },
        "HC01": { id: "HC01", floor: "B2", section: "Handcraft (수예)", x: 45, y: 70, ar_x: 0, ar_y: 4 },
        "CA01": { id: "CA01", floor: "B2", section: "Camping (캠핑)", x: 60, y: 70, ar_x: 2, ar_y: 4 },

        "TR01": { id: "TR01", floor: "B2", section: "Travel (여행)", x: 40, y: 85, ar_x: -2, ar_y: 1 },
        "GA01": { id: "GA01", floor: "B2", section: "Gardening (원예)", x: 65, y: 85, ar_x: 3, ar_y: 1 },
    }
};

function findProductLocation(name) {
    if (!name) return mapData.shelves["C01"];

    // --- B2 Keywords ---
    if (name.includes("샴푸") || name.includes("비누") || name.includes("욕실")) return mapData.shelves["BA01"];
    if (name.includes("청소") || name.includes("밀대")) return mapData.shelves["CL01"];
    if (name.includes("세탁") || name.includes("세제") || name.includes("빨래")) return mapData.shelves["LA01"];
    if (name.includes("득템")) return mapData.shelves["GP01"];
    if (name.includes("일본") || name.includes("수입")) return mapData.shelves["JA01"];
    if (name.includes("수납") || name.includes("바구니")) return mapData.shelves["ST01"];
    if (name.includes("패브릭") || name.includes("이불") || name.includes("쿠션")) return mapData.shelves["HF01"];
    if (name.includes("내추럴")) return mapData.shelves["NC01"];
    if (name.includes("공구") || name.includes("드라이버")) return mapData.shelves["TO01"];
    if (name.includes("스포츠") || name.includes("운동")) return mapData.shelves["SP01"];
    if (name.includes("강아지") || name.includes("반려") || name.includes("사료")) return mapData.shelves["PE01"];
    if (name.includes("뜨개질") || name.includes("수예")) return mapData.shelves["HC01"];
    if (name.includes("캠핑") || name.includes("텐트")) return mapData.shelves["CA01"];
    if (name.includes("주방") || name.includes("그릇") || name.includes("냄비") || name.includes("채반")) return mapData.shelves["KI01"];
    if (name.includes("여행") || name.includes("캐리어")) return mapData.shelves["TR01"];
    if (name.includes("원예") || name.includes("화분") || name.includes("꽃")) return mapData.shelves["GA01"];
    if (name.includes("B2") || name.includes("지하2층")) return mapData.shelves["KI01"];

    // --- B1 Keywords (Existing) ---
    if (name.includes("볼펜") || name.includes("펜") || name.includes("문구")) return mapData.shelves["A01"];
    if (name.includes("노트")) return mapData.shelves["A02"];
    if (name.includes("시즌") || name.includes("크리스마스")) return mapData.shelves["B01"];
    if (name.includes("화장품") || name.includes("립스틱") || name.includes("뷰티")) return mapData.shelves["C01"];
    if (name.includes("건강") || name.includes("비타민") || name.includes("약")) return mapData.shelves["D01"];
    if (name.includes("캐릭터") || name.includes("인형")) return mapData.shelves["E01"];
    if (name.includes("패션") || name.includes("옷") || name.includes("양말")) return mapData.shelves["F01"];
    if (name.includes("파티") || name.includes("장난감")) return mapData.shelves["G01"];
    if (name.includes("인테리어") || name.includes("조명")) return mapData.shelves["H01"];
    if (name.includes("포장") || name.includes("선물")) return mapData.shelves["I01"];
    if (name.includes("디지털") || name.includes("충전기") || name.includes("케이블")) return mapData.shelves["J01"];
    if (name.includes("식품") || name.includes("과자") || name.includes("라면")) return mapData.shelves["K01"];

    // Default
    return mapData.shelves["C01"];
}
