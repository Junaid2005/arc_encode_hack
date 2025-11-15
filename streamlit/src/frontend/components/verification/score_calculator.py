"""
Score calculator module.

Combines on-chain and off-chain verification to compute a final weighted trust score.
Converts wallet summary data to on-chain scores and combines with off-chain scores
using a weighted formula (60% on-chain, 40% off-chain).
"""

from typing import Dict, Any

from .onchain_verifier import OnChainVerifier
from .offchain_verifier import OffChainVerifier


def calculate_final_trust_score(on_chain_score: float, off_chain_score: float) -> int:
    """
    Calculate the final trust score using weighted formula:
    final = 0.6 * on_chain_score + 0.4 * off_chain_score

    Args:
        on_chain_score: On-chain trust score (0-100)
        off_chain_score: Off-chain trust score (0-100)

    Returns:
        Final trust score rounded and clamped between 0-100
    """
    final = 0.85 * on_chain_score + 0.15 * off_chain_score
    # Round to nearest integer and clamp between 0-100
    final = max(0, min(100, round(final)))
    return final


def wallet_summary_to_score(wallet_summary: Dict[str, Any]) -> float:
    """
    Convert wallet summary data to a 0-100 on-chain score.

    Scoring factors:
    - Transaction count (0-30 pts): More transactions = higher score
    - Total value moved (0-30 pts): More value = higher score
    - Unique interactions (0-20 pts): More unique addresses = higher score
    - Wallet age (0-20 pts): Older wallet = higher score
    - Liquidation penalty (0 to -30 pts): Recent/high liquidations reduce score

    Args:
        wallet_summary: Dictionary with wallet metrics from OnChainVerifier

    Returns:
        On-chain score (0-100)
    """
    tx_count = wallet_summary.get("tx_count", 0)
    total_value_moved = wallet_summary.get("total_value_moved", 0.0)
    unique_interactions = wallet_summary.get("unique_interactions", 0)
    wallet_age_days = wallet_summary.get("wallet_age_days", 0.0)

    # Transaction count score (0-30 pts)
    # Scale: 0 tx = 0, 10 tx = 10, 50 tx = 20, 100+ tx = 30
    if tx_count == 0:
        tx_score = 0
    elif tx_count < 10:
        tx_score = tx_count
    elif tx_count < 50:
        tx_score = 10 + (tx_count - 10) * 0.25  # 10-20 range
    else:
        tx_score = min(30, 20 + (tx_count - 50) * 0.2)  # 20-30 range

    # Total value moved score (0-30 pts)
    # Scale: 0 ETH = 0, 1 ETH = 10, 10 ETH = 20, 100+ ETH = 30
    if total_value_moved == 0:
        value_score = 0
    elif total_value_moved < 1:
        value_score = total_value_moved * 10
    elif total_value_moved < 10:
        value_score = 10 + (total_value_moved - 1) * (10 / 9)  # 10-20 range
    else:
        value_score = min(30, 20 + (total_value_moved - 10) * 0.11)  # 20-30 range

    # Unique interactions score (0-20 pts)
    # Scale: 0 = 0, 5 = 10, 20+ = 20
    if unique_interactions == 0:
        interaction_score = 0
    elif unique_interactions < 5:
        interaction_score = unique_interactions * 2
    else:
        interaction_score = min(20, 10 + (unique_interactions - 5) * (10 / 15))

    # Wallet age score (0-20 pts)
    # Scale: 0 days = 0, 30 days = 10, 180+ days = 20
    if wallet_age_days == 0:
        age_score = 0
    elif wallet_age_days < 30:
        age_score = wallet_age_days * (10 / 30)
    else:
        age_score = min(20, 10 + (wallet_age_days - 30) * (10 / 150))

    # Liquidation penalty (0 to -30 pts)
    liquidation_penalty = 0.0
    liquidations_data = wallet_summary.get("liquidations", {})
    if liquidations_data:
        liquidation_count = liquidations_data.get("count", 0)
        days_since_last = liquidations_data.get("daysSinceLast")
        severity = liquidations_data.get("severity", 0.0)
        weighted_count = liquidations_data.get("weightedCount", 0.0)

        if liquidation_count > 0:
            # Base penalty from count: -5 pts per liquidation, capped at -20 pts
            count_penalty = min(20, liquidation_count * 5)

            # Recency penalty: Recent liquidations (< 90 days) add extra penalty
            recency_penalty = 0.0
            if days_since_last is not None and days_since_last < 90:
                # More recent = higher penalty (max -10 pts if < 30 days)
                if days_since_last < 30:
                    recency_penalty = 10
                elif days_since_last < 60:
                    recency_penalty = 7
                else:
                    recency_penalty = 4

            # Severity penalty: High severity (> 0.5) adds penalty
            severity_penalty = 0.0
            if severity > 0.5:
                # High severity = additional -5 to -10 pts
                severity_penalty = min(10, (severity - 0.5) * 20)

            # Weighted count penalty: Accounts for time-weighted liquidation frequency
            weighted_penalty = 0.0
            if weighted_count > 2.0:
                # High weighted count indicates frequent liquidations
                weighted_penalty = min(5, (weighted_count - 2.0) * 2.5)

            liquidation_penalty = -(
                count_penalty + recency_penalty + severity_penalty + weighted_penalty
            )
            # Cap total penalty at -30 pts
            liquidation_penalty = max(-30, liquidation_penalty)

    total_score = (
        tx_score + value_score + interaction_score + age_score + liquidation_penalty
    )
    return min(100, max(0, total_score))


class ScoreCalculator:
    """
    Combines on-chain and off-chain verification to compute a final trust score.
    """

    def __init__(self, chain: str = "ethereum"):
        """
        Initialize the score calculator with on-chain and off-chain verifiers.

        Args:
            chain: Blockchain to use for on-chain verification (default: "ethereum")
        """
        self.onchain_verifier = OnChainVerifier(chain=chain)
        self.offchain_verifier = OffChainVerifier()

    async def compute_score(
        self, wallet_address: str, user_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compute the final trust score by combining on-chain and off-chain scores.

        Args:
            wallet_address: Ethereum wallet address
            user_profile: Dictionary containing user profile data:
                - uploaded_files: Optional list of uploaded file objects
                - email: Optional email address string
                - phone: Optional phone number string
                - name: Optional full name string
                - social_link: Optional social media profile URL string

        Returns:
            Dictionary containing:
                - on_chain_score: On-chain trust score (0-100)
                - off_chain_score: Off-chain trust score (0-100)
                - final_score: Final weighted trust score (0-100)
        """
        # Get on-chain wallet summary
        wallet_summary = await self.onchain_verifier.get_wallet_summary(wallet_address)
        on_chain_score = wallet_summary_to_score(wallet_summary)

        # Get off-chain score
        offchain_result = self.offchain_verifier.compute_offchain_score(
            uploaded_files=user_profile.get("uploaded_files"),
            email=user_profile.get("email"),
            phone=user_profile.get("phone"),
            name=user_profile.get("name"),
            social_link=user_profile.get("social_link"),
        )
        off_chain_score = offchain_result.get("total_offchain_score", 0)

        # Calculate final weighted score
        final_score = calculate_final_trust_score(on_chain_score, off_chain_score)

        return {
            "on_chain_score": round(on_chain_score),
            "off_chain_score": off_chain_score,
            "final_score": final_score,
        }
