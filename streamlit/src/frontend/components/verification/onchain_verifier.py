"""
On-chain verification module.

Provides functionality to fetch and analyze wallet transaction data from the blockchain
using Hypersync. Extracts wallet metrics including transaction count, value moved,
unique interactions, and wallet age. Also detects DeFi liquidation events from Aave V3
and Compound V3.
"""

import math
import asyncio
from typing import Dict, Any, List, Optional

from hypersync import (
    HypersyncClient,
    ClientConfig,
    Query,
    FieldSelection,
    TransactionSelection,
    TransactionField,
    LogSelection,
)


class OnChainVerifier:
    """
    On-chain wallet verification and analysis.
    
    Fetches wallet transaction data from the blockchain using Hypersync and extracts
    key metrics including transaction count, total value moved, unique interactions,
    and wallet age. Also detects DeFi liquidation events from Aave V3 and Compound V3.
    """
    
    # Aave V3 Pool contract address (Ethereum mainnet)
    # Correct address: 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2
    AAVE_V3_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2".lower()
    
    # Compound V3 Comet contract addresses (Ethereum mainnet - USDC market)
    COMPOUND_V3_COMET_USDC = "0xc3d688B66703497DAA19211EEdff47f25384cdc3".lower()
    
    # Event signatures (keccak256 hash of event signature)
    # LiquidationCall(address,address,address,uint256,uint256,address,bool)
    # Computed: keccak256("LiquidationCall(address,address,address,uint256,uint256,address,bool)")
    AAVE_LIQUIDATION_EVENT_TOPIC = "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e1b6c41"
    
    # AbsorbDebt(address,address,uint256,uint256) - Compound V3
    # Computed: keccak256("AbsorbDebt(address,address,uint256,uint256)")
    COMPOUND_ABSORB_DEBT_EVENT_TOPIC = "0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"
    
    # AbsorbCollateral(address,address,uint256,uint256) - Compound V3
    # Computed: keccak256("AbsorbCollateral(address,address,uint256,uint256)")
    COMPOUND_ABSORB_COLLATERAL_EVENT_TOPIC = "0x8b3e96f2b889fa0cbbbbf43777f1cae817d2462b79f3ac07c4170c6f8ade40a2"
    
    def __init__(self, chain: str = "ethereum"):
        # Using the provided token directly in the class
        self.api_key = "547eb877-5324-4821-8e51-bc71dcae2659"
        self.chain = chain
        config = ClientConfig(bearer_token=self.api_key)
        self.client = HypersyncClient(config)

    async def fetch_aave_v3_liquidations(self, address: str, start_block: int, latest_block: int) -> List[Dict[str, Any]]:
        """
        Fetch Aave V3 liquidation events for the given address.
        
        Args:
            address: Wallet address to check (normalized to lowercase)
            start_block: Starting block number
            latest_block: Latest block number
            
        Returns:
            List of liquidation event dictionaries
        """
        events = []
        try:
            # Normalize address
            address = address.lower()
            if not address.startswith("0x"):
                address = "0x" + address
            
            # Pad address to 32 bytes (64 hex chars) for topic matching
            address_clean = address[2:] if address.startswith("0x") else address
            address_padded = "0x" + "0" * (64 - len(address_clean)) + address_clean.lower()
            
            # Query all liquidation events and filter client-side (more reliable than topic filtering)
            # LiquidationCall(address indexed collateralAsset, address indexed debtAsset, address indexed user, ...)
            # topic0 = event signature, topic1 = collateralAsset, topic2 = debtAsset, topic3 = user
            query_all = Query(
                from_block=start_block,
                to_block=latest_block,
                field_selection=FieldSelection(),
                logs=[
                    LogSelection(
                        address=[self.AAVE_V3_POOL],
                        topics=[[self.AAVE_LIQUIDATION_EVENT_TOPIC]],
                    )
                ],
            )
            
            response_all = await self.client.get(query_all)
            all_logs = response_all.data.logs if response_all.data.logs else []
            
            # Filter logs where topic3 (user) matches our address
            logs = []
            for log in all_logs:
                try:
                    # Try different ways to access topics
                    topics = None
                    if hasattr(log, 'topics'):
                        topics = log.topics
                    elif hasattr(log, 'topic'):
                        topics = [log.topic] if log.topic else []
                    elif hasattr(log, 'topics_list'):
                        topics = log.topics_list
                    
                    if not topics:
                        continue
                    
                    # Topics might be a list of strings, or a dict, or individual attributes
                    # Convert to list if needed
                    if isinstance(topics, dict):
                        # If it's a dict, try to get topic0, topic1, etc.
                        topics_list = []
                        for i in range(4):
                            key = f'topic{i}'
                            if key in topics:
                                topics_list.append(topics[key])
                        topics = topics_list
                    elif not isinstance(topics, list):
                        topics = [topics]
                    
                    if len(topics) >= 4:
                        # topic3 is the user address - handle different formats
                        user_topic_raw = topics[3]
                        user_topic = ""
                        
                        if isinstance(user_topic_raw, list):
                            if len(user_topic_raw) > 0:
                                user_topic = str(user_topic_raw[0]).lower()
                        elif isinstance(user_topic_raw, str):
                            user_topic = user_topic_raw.lower()
                        elif user_topic_raw is not None:
                            user_topic = str(user_topic_raw).lower()
                        
                        # Normalize the topic (remove 0x if needed, ensure proper padding)
                        if user_topic and user_topic.startswith('0x'):
                            # Ensure it's 66 chars (0x + 64 hex)
                            if len(user_topic) < 66:
                                user_topic = '0x' + '0' * (66 - len(user_topic)) + user_topic[2:]
                        
                        # Compare with padded address
                        if user_topic == address_padded.lower():
                            logs.append(log)
                except Exception as e:
                    continue
            
            for log in logs:
                try:
                    # Extract data from log - try multiple ways to access attributes
                    topics = None
                    if hasattr(log, 'topics'):
                        topics = log.topics
                    elif hasattr(log, 'topic'):
                        topics = [log.topic] if log.topic else []
                    
                    if isinstance(topics, dict):
                        topics = [topics.get(f'topic{i}', '') for i in range(4)]
                    elif not isinstance(topics, list):
                        topics = [topics] if topics else []
                    
                    data = getattr(log, 'data', '0x') or '0x'
                    tx_hash = getattr(log, 'transaction_hash', '') or getattr(log, 'hash', '') or ''
                    block_number = getattr(log, 'block_number', 0) or 0
                    
                    # Verify this is for our address (double-check topic3)
                    if len(topics) >= 4:
                        user_topic_raw = topics[3]
                        user_topic = ""
                        if isinstance(user_topic_raw, list) and len(user_topic_raw) > 0:
                            user_topic = str(user_topic_raw[0]).lower()
                        elif user_topic_raw is not None:
                            user_topic = str(user_topic_raw).lower()
                        
                        if user_topic and user_topic.startswith('0x') and len(user_topic) < 66:
                            user_topic = '0x' + '0' * (66 - len(user_topic)) + user_topic[2:]
                        
                        if user_topic != address_padded.lower():
                            continue  # Skip if not our address
                    
                    # Parse data (first 32 bytes = debtToCover, next 32 bytes = liquidatedCollateralAmount)
                    if data and len(data) >= 130:  # 0x + 128 hex chars = 64 bytes
                        debt_to_cover_hex = "0x" + data[2:66]
                        collateral_seized_hex = "0x" + data[66:130]
                        
                        debt_to_cover = int(debt_to_cover_hex, 16) if debt_to_cover_hex != "0x" else 0
                        collateral_seized = int(collateral_seized_hex, 16) if collateral_seized_hex != "0x" else 0
                    else:
                        debt_to_cover = 0
                        collateral_seized = 0
                    
                    # Approximate USD values (simplified: assume 1e18 = $1 for now, will be refined with actual pricing)
                    # For now, use raw values as placeholders
                    amount_repaid_usd = debt_to_cover / 1e18  # Placeholder
                    collateral_seized_usd = collateral_seized / 1e18  # Placeholder
                    
                    events.append({
                        "txHash": tx_hash,
                        "protocol": "AAVE_V3",
                        "blockNumber": block_number,
                        "amountRepaidUSD": amount_repaid_usd,
                        "collateralSeizedUSD": collateral_seized_usd,
                        "percentLiquidated": 0.0,  # Not available from event
                    })
                except Exception as e:
                    continue
                    
        except Exception as e:
            pass
            
        return events

    async def fetch_compound_v3_liquidations(self, address: str, start_block: int, latest_block: int) -> List[Dict[str, Any]]:
        """
        Fetch Compound V3 liquidation events for the given address.
        
        Args:
            address: Wallet address to check (normalized to lowercase)
            start_block: Starting block number
            latest_block: Latest block number
            
        Returns:
            List of liquidation event dictionaries
        """
        events = []
        try:
            # Normalize address
            address = address.lower()
            if not address.startswith("0x"):
                address = "0x" + address
            
            # Pad address to 32 bytes (64 hex chars) for topic matching
            address_clean = address[2:] if address.startswith("0x") else address
            address_padded = "0x" + "0" * (64 - len(address_clean)) + address_clean.lower()
            
            # Query all events in parallel and filter client-side (faster and more reliable)
            # AbsorbDebt(address indexed absorber, address indexed borrower, uint256 basePaidOut, uint256 usdValue)
            # AbsorbCollateral(address indexed absorber, address indexed borrower, uint256 collateralAbsorbed, uint256 usdValue)
            # topic0 = event signature, topic1 = absorber, topic2 = borrower
            
            query_debt_all = Query(
                from_block=start_block,
                to_block=latest_block,
                field_selection=FieldSelection(),
                logs=[
                    LogSelection(
                        address=[self.COMPOUND_V3_COMET_USDC],
                        topics=[[self.COMPOUND_ABSORB_DEBT_EVENT_TOPIC]],
                    )
                ],
            )
            query_collateral_all = Query(
                from_block=start_block,
                to_block=latest_block,
                field_selection=FieldSelection(),
                logs=[
                    LogSelection(
                        address=[self.COMPOUND_V3_COMET_USDC],
                        topics=[[self.COMPOUND_ABSORB_COLLATERAL_EVENT_TOPIC]],
                    )
                ],
            )
            
            # Execute both queries in parallel
            response_debt_all, response_collateral_all = await asyncio.gather(
                self.client.get(query_debt_all),
                self.client.get(query_collateral_all)
            )
            
            all_logs_debt = response_debt_all.data.logs if response_debt_all.data.logs else []
            all_logs_collateral = response_collateral_all.data.logs if response_collateral_all.data.logs else []
            
            # Filter by borrower address (topic2) - improved topic parsing
            logs_debt = []
            for log in all_logs_debt:
                try:
                    topics = None
                    if hasattr(log, 'topics'):
                        topics = log.topics
                    elif hasattr(log, 'topic'):
                        topics = [log.topic] if log.topic else []
                    
                    if isinstance(topics, dict):
                        topics = [topics.get(f'topic{i}', '') for i in range(3)]
                    elif not isinstance(topics, list):
                        topics = [topics] if topics else []
                    
                    if len(topics) >= 3:
                        borrower_topic_raw = topics[2]
                        borrower_topic = ""
                        if isinstance(borrower_topic_raw, list) and len(borrower_topic_raw) > 0:
                            borrower_topic = str(borrower_topic_raw[0]).lower()
                        elif borrower_topic_raw is not None:
                            borrower_topic = str(borrower_topic_raw).lower()
                        
                        if borrower_topic and borrower_topic.startswith('0x') and len(borrower_topic) < 66:
                            borrower_topic = '0x' + '0' * (66 - len(borrower_topic)) + borrower_topic[2:]
                        
                        if borrower_topic == address_padded.lower():
                            logs_debt.append(log)
                except Exception as e:
                    continue
            
            logs_collateral = []
            for log in all_logs_collateral:
                try:
                    topics = None
                    if hasattr(log, 'topics'):
                        topics = log.topics
                    elif hasattr(log, 'topic'):
                        topics = [log.topic] if log.topic else []
                    
                    if isinstance(topics, dict):
                        topics = [topics.get(f'topic{i}', '') for i in range(3)]
                    elif not isinstance(topics, list):
                        topics = [topics] if topics else []
                    
                    if len(topics) >= 3:
                        borrower_topic_raw = topics[2]
                        borrower_topic = ""
                        if isinstance(borrower_topic_raw, list) and len(borrower_topic_raw) > 0:
                            borrower_topic = str(borrower_topic_raw[0]).lower()
                        elif borrower_topic_raw is not None:
                            borrower_topic = str(borrower_topic_raw).lower()
                        
                        if borrower_topic and borrower_topic.startswith('0x') and len(borrower_topic) < 66:
                            borrower_topic = '0x' + '0' * (66 - len(borrower_topic)) + borrower_topic[2:]
                        
                        if borrower_topic == address_padded.lower():
                            logs_collateral.append(log)
                except Exception as e:
                    continue
            
            # Process AbsorbDebt events
            for log in logs_debt:
                try:
                    topics = log.topics if hasattr(log, 'topics') else []
                    # Verify this is for our address (double-check topic2)
                    if len(topics) >= 3:
                        borrower_topic_raw = topics[2]
                        if isinstance(borrower_topic_raw, list) and len(borrower_topic_raw) > 0:
                            borrower_topic = borrower_topic_raw[0].lower() if isinstance(borrower_topic_raw[0], str) else ""
                        elif isinstance(borrower_topic_raw, str):
                            borrower_topic = borrower_topic_raw.lower()
                        else:
                            continue
                        
                        if borrower_topic != address_padded.lower():
                            continue  # Skip if not our address
                    
                    data = log.data if hasattr(log, 'data') else "0x"
                    tx_hash = log.transaction_hash if hasattr(log, 'transaction_hash') else ""
                    block_number = log.block_number if hasattr(log, 'block_number') else 0
                    
                    # Parse data (first 32 bytes = basePaidOut, next 32 bytes = usdValue)
                    if data and len(data) >= 130:
                        base_paid_hex = "0x" + data[2:66]
                        usd_value_hex = "0x" + data[66:130]
                        
                        base_paid = int(base_paid_hex, 16) if base_paid_hex != "0x" else 0
                        usd_value = int(usd_value_hex, 16) if usd_value_hex != "0x" else 0
                    else:
                        base_paid = 0
                        usd_value = 0
                    
                    amount_repaid_usd = usd_value / 1e18 if usd_value > 0 else base_paid / 1e18
                    
                    events.append({
                        "txHash": tx_hash,
                        "protocol": "COMPOUND_V3",
                        "blockNumber": block_number,
                        "amountRepaidUSD": amount_repaid_usd,
                        "collateralSeizedUSD": 0.0,  # Will be filled by AbsorbCollateral event
                        "percentLiquidated": 0.0,
                    })
                except Exception as e:
                    continue
            
            # Process AbsorbCollateral events
            for log in logs_collateral:
                try:
                    topics = log.topics if hasattr(log, 'topics') else []
                    # Verify this is for our address (double-check topic2)
                    if len(topics) >= 3:
                        borrower_topic_raw = topics[2]
                        if isinstance(borrower_topic_raw, list) and len(borrower_topic_raw) > 0:
                            borrower_topic = borrower_topic_raw[0].lower() if isinstance(borrower_topic_raw[0], str) else ""
                        elif isinstance(borrower_topic_raw, str):
                            borrower_topic = borrower_topic_raw.lower()
                        else:
                            continue
                        
                        if borrower_topic != address_padded.lower():
                            continue  # Skip if not our address
                    
                    data = log.data if hasattr(log, 'data') else "0x"
                    tx_hash = log.transaction_hash if hasattr(log, 'transaction_hash') else ""
                    block_number = log.block_number if hasattr(log, 'block_number') else 0
                    
                    # Parse data (first 32 bytes = collateralAbsorbed, next 32 bytes = usdValue)
                    if data and len(data) >= 130:
                        collateral_hex = "0x" + data[2:66]
                        usd_value_hex = "0x" + data[66:130]
                        
                        collateral = int(collateral_hex, 16) if collateral_hex != "0x" else 0
                        usd_value = int(usd_value_hex, 16) if usd_value_hex != "0x" else 0
                    else:
                        collateral = 0
                        usd_value = 0
                    
                    collateral_seized_usd = usd_value / 1e18 if usd_value > 0 else collateral / 1e18
                    
                    # Try to match with existing AbsorbDebt event for same tx, otherwise create new event
                    matched = False
                    for event in events:
                        if event["txHash"] == tx_hash and event["protocol"] == "COMPOUND_V3":
                            event["collateralSeizedUSD"] = collateral_seized_usd
                            matched = True
                            break
                    
                    if not matched:
                        events.append({
                            "txHash": tx_hash,
                            "protocol": "COMPOUND_V3",
                            "blockNumber": block_number,
                            "amountRepaidUSD": 0.0,  # Debt event might come separately
                            "collateralSeizedUSD": collateral_seized_usd,
                            "percentLiquidated": 0.0,
                        })
                except Exception as e:
                    continue
                    
        except Exception as e:
            pass
            
        return events

    def compute_liquidation_features(
        self, 
        events: List[Dict[str, Any]], 
        total_supplies_usd: float,
        latest_block: int,
        blocks_per_day: float = 7200.0
    ) -> Dict[str, Any]:
        """
        Compute derived liquidation features from events.
        
        Args:
            events: List of liquidation event dictionaries
            total_supplies_usd: Total supplies in USD (for severity calculation)
            latest_block: Latest block number
            blocks_per_day: Approximate blocks per day (default ~7200)
            
        Returns:
            Dictionary with computed liquidation features
        """
        if not events:
            return {
                "count": 0,
                "totalAmountUSD": 0.0,
                "daysSinceLast": None,
                "severity": 0.0,
                "weightedCount": 0.0,
                "events": [],
            }
        
        total_liquidations = len(events)
        total_liquidated_amount_usd = sum(event.get("collateralSeizedUSD", 0.0) for event in events)
        
        # Find last liquidation
        last_liquidation_block = max((event.get("blockNumber", 0) for event in events), default=0)
        last_liquidation_at = last_liquidation_block
        days_since_last = (
            (latest_block - last_liquidation_block) / blocks_per_day
            if last_liquidation_block > 0 else None
        )
        
        # Compute severity
        severity = total_liquidated_amount_usd / max(total_supplies_usd, 1.0)
        
        # Compute weighted count (λ ≈ 0.01)
        lambda_decay = 0.01
        weighted_count = 0.0
        for event in events:
            block_number = event.get("blockNumber", latest_block)
            age_days = (latest_block - block_number) / blocks_per_day
            weighted_count += math.exp(-lambda_decay * age_days)
        
        return {
            "count": total_liquidations,
            "totalAmountUSD": total_liquidated_amount_usd,
            "daysSinceLast": days_since_last,
            "severity": severity,
            "weightedCount": weighted_count,
            "events": events,
        }

    async def get_wallet_summary(self, address: str) -> Dict[str, Any]:
        # Normalize address
        address = address.lower()

        # Get latest block height
        latest_block = await self.client.get_height()

        # Calculate start block for transactions (last ~6 months, ~500k blocks)
        start_block = max(0, latest_block - 500_000)
        
        # Use wider range for liquidation queries (last ~2 years) to catch older liquidations
        liquidation_start_block = max(0, latest_block - 2_000_000)

        # Create query to fetch transactions for this address
        query = Query(
            from_block=start_block,
            to_block=latest_block,
            field_selection=FieldSelection(
                transaction=[
                    TransactionField.VALUE,
                    TransactionField.TO,
                    TransactionField.FROM,
                    TransactionField.BLOCK_NUMBER,
                ]
            ),
            transactions=[
                TransactionSelection(
                    from_=[address],
                ),
                TransactionSelection(
                    to=[address],
                ),
            ],
        )

        # Execute query
        response = await self.client.get(query)
        txs = response.data.transactions

        # --- Feature Extraction ---
        tx_count = len(txs)

        # Convert value from hex string (wei) to ETH
        total_value_moved = 0.0
        for tx in txs:
            if tx.value:
                try:
                    # Value is a hex string, convert to int then to ETH
                    value_wei = int(tx.value, 16) if tx.value.startswith('0x') else int(tx.value)
                    total_value_moved += value_wei / 1e18
                except (ValueError, AttributeError):
                    pass

        unique_interactions = len(
            set(tx.to for tx in txs if tx.to)
        )

        block_numbers = [tx.block_number for tx in txs if tx.block_number is not None]
        first_seen_block = min(block_numbers) if block_numbers else None
        wallet_age = (
            (latest_block - first_seen_block) / 7200
            if first_seen_block else 0
        )  # approx days

        # Fetch liquidation events in parallel for speed (use wider block range for liquidations)
        aave_liquidations, compound_liquidations = await asyncio.gather(
            self.fetch_aave_v3_liquidations(address, liquidation_start_block, latest_block),
            self.fetch_compound_v3_liquidations(address, liquidation_start_block, latest_block)
        )
        
        # Combine all liquidation events
        all_liquidation_events = aave_liquidations + compound_liquidations
        
        # Compute liquidation features
        # Use total_value_moved as a proxy for totalSuppliesUSD (can be refined later)
        total_supplies_usd = max(total_value_moved * 2000, 1.0)  # Rough ETH price estimate, fallback to 1
        liquidation_features = self.compute_liquidation_features(
            all_liquidation_events,
            total_supplies_usd,
            latest_block,
        )
        
        result = {
            "address": address,
            "tx_count": tx_count,
            "total_value_moved": total_value_moved,
            "unique_interactions": unique_interactions,
            "wallet_age_days": wallet_age,
            "liquidations": liquidation_features,
        }
        
        return result
