/**
 * Simple global search state store (no external dependencies)
 * Uses module-level state + event emitter pattern for cross-page state sharing
 */

import type { SearchResponse, ProductResult } from "@/types/search";

// ============================================================================
// State
// ============================================================================

export interface SearchState {
    // Query
    query: string;
    inputType: "text" | "voice";

    // Search results
    searchResponse: SearchResponse | null;
    isLoading: boolean;
    error: string | null;

    // Session
    sessionId: string;
    clarificationCount: number;
    history: Array<{ role: string; content: string }>;
}

let state: SearchState = {
    query: "",
    inputType: "text",
    searchResponse: null,
    isLoading: false,
    error: null,
    sessionId: `session_${Date.now()}`,
    clarificationCount: 0,
    history: [],
};

// ============================================================================
// Getters
// ============================================================================

export function getSearchState(): SearchState {
    return { ...state };
}

export function getTopProduct(): ProductResult | null {
    if (!state.searchResponse?.top3?.length) return null;
    return state.searchResponse.top3.find((p) => p.is_top1) || state.searchResponse.top3[0];
}

export function getRelatedProducts(): ProductResult[] {
    if (!state.searchResponse?.top3?.length) return [];
    const top1 = getTopProduct();
    return state.searchResponse.top3.filter(
        (p) => p.product_id !== top1?.product_id
    );
}

export function hasResults(): boolean {
    return (state.searchResponse?.top3?.length ?? 0) > 0;
}

export function needsClarification(): boolean {
    return state.searchResponse?.needs_clarification ?? false;
}

// ============================================================================
// Setters
// ============================================================================

export function setQuery(query: string, inputType: "text" | "voice" = "text"): void {
    state = { ...state, query, inputType };
}

export function setSearchResponse(response: SearchResponse | null): void {
    state = {
        ...state,
        searchResponse: response,
        isLoading: false,
        error: null,
        clarificationCount: response?.clarification_count ?? state.clarificationCount,
    };
}

export function setLoading(isLoading: boolean): void {
    state = { ...state, isLoading, error: null };
}

export function setError(error: string): void {
    state = { ...state, error, isLoading: false };
}

export function addToHistory(role: string, content: string): void {
    state = {
        ...state,
        history: [...state.history, { role, content }],
    };
}

export function resetSearch(): void {
    state = {
        query: "",
        inputType: "text",
        searchResponse: null,
        isLoading: false,
        error: null,
        sessionId: `session_${Date.now()}`,
        clarificationCount: 0,
        history: [],
    };
}

export function incrementClarification(): void {
    state = {
        ...state,
        clarificationCount: state.clarificationCount + 1,
    };
}
