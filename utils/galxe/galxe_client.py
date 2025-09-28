import asyncio
import random
import time
import uuid

from loguru import logger

from data.settings import Settings
from libs.base import Base
from libs.eth_async.client import Client
from libs.eth_async.data.models import Network, Networks, TokenAmount
from utils.browser import Browser
from utils.captcha.captcha_handler import CaptchaHandler
from utils.db_api.models import Wallet
from utils.retry import async_retry

from .galxe_auth import AuthClient
from .galxe_onchain import GalxeOnchain
from .galxe_utils import generate_ga_cookie_value, make_x_unique_link_id


class GalxeClient:
    BASE_LINK = "https://graphigo.prd.galaxy.eco/query"
    SAVE_LINK = "https://savings-graphigo.prd.latch.io/query"

    def __init__(self, wallet: Wallet, client: Client):
        self.wallet = wallet
        self.client = client
        self.browser = Browser(wallet=self.wallet)
        self.base = Base(client=self.client, wallet=self.wallet)
        self.auth_client = AuthClient(wallet=self.wallet, browser=self.browser, client=self.client)
        self.galxe_onchain = GalxeOnchain(wallet=self.wallet, browser=self.browser, client=self.client)
        self.bearer_token = None
        self.galxe_id = ""
        self.client_id = ""
        self.headers = {}

    def update_headers(self, suffix:str =  ""):
        return self.headers.update({
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'content-type': 'application/json',
            'Sec-GPC': '1',
            'platform': 'web',
            "request-id": str(uuid.uuid4()) ,
            'Origin': 'https://app.galxe.com',
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            'Sec-Fetch-Site': 'cross-site',
            "Priority": "u=4",
            'x-unique-link-id': f'{make_x_unique_link_id(galxe_id=self.galxe_id, suffix=suffix)}',
            'authorization': self.bearer_token,
            'device-id': f'ga-user-{self.client_id}',
            'x-unique-client-id': f'ga-user-{self.client_id}',
        })

    @async_retry()
    async def request(self, json_data, use_save: bool = False, suffix: str = ""):
        self.update_headers(suffix)
        if use_save:
            response = await self.browser.post(url=self.SAVE_LINK, json=json_data, headers=self.headers)
        else:
            logger.debug(self.headers)
            response = await self.browser.post(url=self.BASE_LINK, json=json_data, headers=self.headers)
        data = response.json()
        logger.debug(data)
        return data

    async def choose_client_for_subscription(self):
        network_values = [Networks.Base, Networks.Polygon, Networks.Arbitrum, Networks.BSC]
        exchange_rate = await self.get_exchange_rate()
        eth_rate = exchange_rate['data']['GetExchangeRate'][0]['rate']
        pol_rate = exchange_rate['data']['GetExchangeRate'][6]['rate']
        bnb_rate = exchange_rate['data']['GetExchangeRate'][5]['rate']
        for network in network_values:
            try:
                client = Client(private_key=self.client.account._private_key.hex(), network=network, proxy=self.client.proxy)
                native_balance = await client.wallet.balance()
                if network.name == 'polygon':
                    rate = pol_rate
                    subscription_usd = 1.99
                elif network.name == 'bsc':
                    rate = bnb_rate
                    subscription_usd = 1.99
                else:
                    rate = eth_rate
                    subscription_usd = 2.01
                calculate_deposit = TokenAmount(amount=self.calculate_deposit(exchange_rate_hex=rate, subscription_usd=subscription_usd))
                logger.debug(f"{self.wallet} native balance in {network.name}: {native_balance.Ether}")
                logger.debug(f"{self.wallet} calculated deposit {calculate_deposit.Ether}")
                if native_balance.Ether < calculate_deposit.Ether:
                    continue
                else:
                    return client, '0x0000000000000000000000000000000000000000', calculate_deposit
            except Exception as e:
                logger.warning(f"{self.wallet} can't check network {network.name} error: {e}")
                continue
        return None, None, None

    def calculate_deposit(self, exchange_rate_hex, subscription_usd=2.01, decimals=18):
        rate_int = int(exchange_rate_hex, 0) 
        deposit = subscription_usd * (10 ** decimals) / rate_int
        return deposit

    async def get_exchange_rate(self):
        json_data = {
            'operationName': 'GetExchangeRate',
            'variables': {
                'tokens': [
                    {
                        'chainId': 1,
                        'addr': '0x0000000000000000000000000000000000000000',
                    },
                    {
                        'chainId': 1,
                        'addr': '0x4c9EDD5852cd905f086C759E8383e09bff1E68B3',
                    },
                    {
                        'chainId': 1,
                        'addr': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
                    },
                    {
                        'chainId': 1,
                        'addr': '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                    },
                    {
                        'chainId': 1,
                        'addr': '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
                    },
                    {
                        'chainId': 56,
                        'addr': '0x0000000000000000000000000000000000000000',
                    },
                    {
                        'chainId': 137,
                        'addr': '0x0000000000000000000000000000000000000000',
                    },
                    {
                        'chainId': 1625,
                        'addr': '0x0000000000000000000000000000000000000000',
                    },
                ],
            },
            'query': 'query GetExchangeRate($tokens: [TokenInput!]!) {\n  GetExchangeRate(tokens: $tokens) {\n    token {\n      chainId\n      addr\n      logo\n      symbol\n      decimals\n      __typename\n    }\n    rate\n    __typename\n  }\n}',
        }
        return await self.request(json_data=json_data, use_save=True)

    async def _get_price(self, coin_id):
        if coin_id.upper() == 'ETH':
            coin_id = 'ethereum'
        elif coin_id.upper() == 'BNB':
            coin_id = 'binancecoin'
        elif coin_id.upper() == 'POL':
            coin_id = 'polygon-ecosystem-token'
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        request = await self.browser.get(url=url)
        data = request.json()
        price =  float(data[coin_id]['usd'])
        return price

    async def choose_available_client(self):
        network_values = [value for key, value in Networks.__dict__.items() if isinstance(value, Network)]
        random.shuffle(network_values)
        for network in network_values:
            if network.name in Settings().network_for_bridge:
                try:
                    client = Client(private_key=self.client.account._private_key.hex(), network=network, proxy=self.client.proxy)
                    balance = await client.wallet.balance()
                    if balance.Ether > Settings().random_eth_for_bridge_max:
                        base_client = Base(client=client, wallet=self.wallet)
                        return base_client
                except Exception as e:
                    logger.warning(f"{self.wallet} can't check network {network.name} error: {e}")
                    continue

    async def update_points_and_rank(self, campaign_id: int):
        data = await self.get_points_and_rank(campaign_id=campaign_id)
        points = data["data"]["space"]["addressLoyaltyPoints"]["points"]
        rank = data["data"]["space"]["addressLoyaltyPoints"]["rank"]
        return points, rank

    async def delete_social_account(self, social: str):
        json_data = {
            "operationName": "DeleteSocialAccount",
            "variables": {
                "input": {
                    "address": f"EVM:{self.client.account.address}",
                    "type": f"{social.upper()}",
                },
            },
            "query": "mutation DeleteSocialAccount($input: DeleteSocialAccountInput!) {\n  deleteSocialAccount(input: $input) {\n    code\n    message\n    __typename\n  }\n}",
        }
        return await self.request(json_data=json_data)

    async def connect_twitter(self, tweet_url: str):
        json_data = {
            "operationName": "checkTwitterAccount",
            "variables": {
                "input": {
                    "address": f"EVM:{self.client.account.address}",
                    "tweetURL": f"{tweet_url}",
                },
            },
            "query": "mutation checkTwitterAccount($input: VerifyTwitterAccountInput!) {\n  checkTwitterAccount(input: $input) {\n    address\n    twitterUserID\n    twitterUserName\n    __typename\n  }\n}",
        }

        await self.request(json_data=json_data)
        json_data = {
            "operationName": "VerifyTwitterAccount",
            "variables": {
                "input": {
                    "address": f"EVM:{self.client.account.address}",
                    "tweetURL": f"{tweet_url}",
                },
            },
            "query": "mutation VerifyTwitterAccount($input: VerifyTwitterAccountInput!) {\n  verifyTwitterAccount(input: $input) {\n    address\n    twitterUserID\n    twitterUserName\n    __typename\n  }\n}",
        }
        return await self.request(json_data=json_data)

    async def get_points_and_rank(self, campaign_id: int):
        json_data = {
            "operationName": "SpaceLoyaltyPoints",
            "variables": {
                "id": campaign_id,
                "address": f"EVM:{self.client.account.address}",
            },
            "query": "query SpaceLoyaltyPoints($id: Int, $address: String!, $seasonId: Int) {\n  space(id: $id) {\n    id\n    addressLoyaltyPoints(address: $address, sprintId: $seasonId) {\n      id\n      points\n      rank\n      __typename\n    }\n    __typename\n  }\n}",
        }
        return await self.request(json_data=json_data)

    async def handle_bridge(self):
        base_client = await self.choose_available_client()
        if not base_client:
            logger.warning(f"{self.wallet} no one Network can be choisen for ETH transfer")
            return False
        start_balance = await self.client.wallet.balance()
        amount_for_bridge = random.uniform(Settings().random_eth_for_bridge_min, Settings().random_eth_for_bridge_max)
        bridge = await self.galxe_onchain.gas_zip_bridge(client=base_client, amount=TokenAmount(amount_for_bridge))
        if not bridge:
            return False
        return await self.wait_deposit(start_balance=start_balance)

    async def wait_deposit(self, start_balance: TokenAmount):
        timeout = 600
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.warning(f"{self.wallet} deposit to gravity did not arrive after {timeout} seconds")
                return False

            logger.info(f"{self.wallet} waiting for deposit to gravity (elapsed: {int(elapsed)}s)")
            balance = await self.client.wallet.balance()

            if start_balance.Wei < balance.Wei:
                logger.info(f"{self.wallet} deposit detected")
                return True

            await asyncio.sleep(5)

    async def claim_points(self, campaign_id: str):
        info = await self.get_campaign_info(campaign_id=campaign_id)
        info = info["data"]["campaign"]
        chain = info["chain"]
        params = self._get_claim_params(info)
        if not params:
            return False
        captcha = await self.get_captcha('PrepareParticipate')
        if params["pointMintAmount"] > 0 and params["mintCount"] > 0:
            params["pointMintAmount"] = 0
        logger.debug(info)
        logger.debug(captcha)
        captcha = await self.get_captcha("PrepareParticipate")
        prepare = await self.prepare_participate(
            campaign_id=campaign_id,
            chain=chain,
            capthca=captcha,
            mint_count=params["mintCount"],
            point_mint_amount=params["pointMintAmount"],
        )
        prepare_data = prepare["data"]["prepareParticipate"]["loyaltyPointsTxResp"]
        loyalty_point_address = prepare_data["loyaltyPointContract"]
        loyalty_point_address = self.client.w3.to_checksum_address(loyalty_point_address)
        verify_ids = prepare_data["VerifyIDs"]
        signature = prepare_data["signature"]
        claim_fee = prepare_data["claimFeeAmount"]
        balance = await self.client.wallet.balance()
        if balance.Wei <= int(claim_fee):
            bridge = await self.handle_bridge()
            if not bridge:
                return False
        amounts = prepare_data["Points"]
        amounts = [TokenAmount(amount).Wei for amount in amounts]
        claim = await self.galxe_onchain.handle_claim_onchain_points(
            loyalty_point_address=loyalty_point_address, verify_ids=verify_ids, amounts=amounts, claim_fee=claim_fee, signature=signature
        )
        return claim

    async def get_captcha(self, action: str):
        try:
            GALXE_CAPTCHA_ID = "244bcb8b9846215df5af4c624a750db4"
            captcha_handler = CaptchaHandler(wallet=self.wallet)
            solution = await captcha_handler.recaptcha_handle(
                websiteURL="https://app.galxe.com/quest", captcha_id=GALXE_CAPTCHA_ID, challenge=action
            )
            return {
                "lotNumber": solution["lot_number"],
                "captchaOutput": solution["captcha_output"],
                "passToken": solution["pass_token"],
                "genTime": solution["gen_time"],
            }
        except Exception as e:
            raise Exception(f"Failed to solve captcha: {str(e)}")

    async def auth(self):
        bearer_token = await self.auth_client.login()
        self.bearer_token = bearer_token
        session = await self.session()
        self.galxe_id = session['data']['addressInfo']['id']
        self.client_id = generate_ga_cookie_value()

    async def session(self):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            "operationName": "BasicUserInfo",
            "variables": {
                "address": f"EVM:{self.wallet.address}",
            },
            "query": "query BasicUserInfo($address: String!) {\n  addressInfo(address: $address) {\n    id\n    username\n    avatar\n    address\n    evmAddressSecondary {\n      address\n      __typename\n    }\n    userLevel {\n      level {\n        name\n        logo\n        minExp\n        maxExp\n        value\n        __typename\n      }\n      exp\n      gold\n      ggRecall\n      __typename\n    }\n    ggInviteeInfo {\n      questCount\n      ggCount\n      __typename\n    }\n    ggInviteCode\n    ggInviter {\n      id\n      username\n      __typename\n    }\n    isBot\n    hasEmail\n    solanaAddress\n    aptosAddress\n    seiAddress\n    injectiveAddress\n    flowAddress\n    starknetAddress\n    bitcoinAddress\n    suiAddress\n    stacksAddress\n    azeroAddress\n    archwayAddress\n    bitcoinSignetAddress\n    xrplAddress\n    algorandAddress\n    tonAddress\n    kadenaAddress\n    hasEvmAddress\n    hasSolanaAddress\n    hasAptosAddress\n    hasInjectiveAddress\n    hasFlowAddress\n    hasStarknetAddress\n    hasBitcoinAddress\n    hasSuiAddress\n    hasStacksAddress\n    hasAzeroAddress\n    hasArchwayAddress\n    hasBitcoinSignetAddress\n    hasXrplAddress\n    hasAlgorandAddress\n    hasTonAddress\n    hasKadenaAddress\n    hasTwitter\n    hasGithub\n    hasDiscord\n    hasTelegram\n    hasWorldcoin\n    displayEmail\n    displayTwitter\n    displayGithub\n    displayDiscord\n    displayTelegram\n    displayWorldcoin\n    displayNamePref\n    email\n    twitterUserID\n    twitterUserName\n    githubUserID\n    githubUserName\n    discordUserID\n    discordUserName\n    telegramUserID\n    telegramUserName\n    worldcoinID\n    enableEmailSubs\n    subscriptions\n    isWhitelisted\n    isInvited\n    isAdmin\n    accessToken\n    humanityType\n    __typename\n  }\n}",
        }
        return await self.request(json_data=json_data)

    async def read_quiz(self, cred_id):
        json_data = {
            "operationName": "readQuiz",
            "variables": {
                "id": f"{cred_id}",
            },
            "query": "query readQuiz($id: ID!) {\n  credential(id: $id) {\n    ...CredQuizFrag\n    __typename\n  }\n}\n\nfragment CredQuizFrag on Cred {\n  metadata {\n    quiz {\n      material\n      quizzes {\n        title\n        type\n        alvaHints\n        items {\n          value\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  __typename\n}",
        }
        return await self.request(json_data=json_data)

    async def sync_quiz(self, cred_id, answers: list):
        await self.read_quiz(cred_id=cred_id)
        json_data = {
            "operationName": "SyncCredentialValue",
            "variables": {
                "input": {
                    "syncOptions": {
                        "credId": f"{cred_id}",
                        "address": f"EVM:{self.client.account.address}",
                        "quiz": {"answers": answers},
                    },
                },
            },
            "query": "mutation SyncCredentialValue($input: SyncCredentialValueInput!) {\n  syncCredentialValue(input: $input) {\n    value {\n      address\n      spaceUsers {\n        follow\n        points\n        participations\n        __typename\n      }\n      campaignReferral {\n        count\n        __typename\n      }\n      galxePassport {\n        eligible\n        lastSelfieTimestamp\n        __typename\n      }\n      spacePoint {\n        points\n        __typename\n      }\n      spaceParticipation {\n        participations\n        __typename\n      }\n      gitcoinPassport {\n        score\n        lastScoreTimestamp\n        __typename\n      }\n      walletBalance {\n        balance\n        __typename\n      }\n      multiDimension {\n        value\n        __typename\n      }\n      allow\n      survey {\n        answers\n        __typename\n      }\n      quiz {\n        allow\n        correct\n        __typename\n      }\n      prediction {\n        isCorrect\n        __typename\n      }\n      spaceFollower {\n        follow\n        __typename\n      }\n      __typename\n    }\n    message\n    __typename\n  }\n}",
        }
        return await self.request(json_data=json_data)

    async def add_type(self, cred_id, campaign_id):
        captcha = await self.get_captcha("AddTypedCredentialItems")
        captcha.update({"encryptedData": ""})
        json_data = {
            "operationName": "AddTypedCredentialItems",
            "variables": {
                "input": {
                    "credId": f"{cred_id}",
                    "campaignId": f"{campaign_id}",
                    "operation": "APPEND",
                    "items": [
                        f"EVM:{self.client.account.address}",
                    ],
                    "captcha": captcha,
                },
            },
            "query": "mutation AddTypedCredentialItems($input: MutateTypedCredItemInput!) {\n  typedCredentialItems(input: $input) {\n    id\n    __typename\n  }\n}",
        }
        await self.request(json_data=json_data)

    async def sync_twitter_quest(self, cred_id, campaign_id):
        await self.add_type(cred_id=cred_id, campaign_id=campaign_id)
        json_data = {
            "operationName": "TwitterOauth2Status",
            "variables": {},
            "query": "query TwitterOauth2Status {\n  twitterOauth2Status {\n    oauthRateLimited\n    __typename\n  }\n}",
        }
        await self.request(json_data=json_data)
        json_data = {
            "operationName": "OauthAddress",
            "variables": {
                "address": f"EVM:{self.client.account.address}",
            },
            "query": "query OauthAddress($address: String!) {\n  addressInfo(address: $address) {\n    id\n    isVerifiedTwitterOauth2\n    isVerifiedDiscordOauth2\n    __typename\n  }\n}",
        }
        await self.request(json_data=json_data)

        captcha = await self.get_captcha("SyncCredentialValue")
        captcha.update({"encryptedData": ""})
        json_data = {
            "operationName": "SyncCredentialValue",
            "variables": {
                "input": {
                    "syncOptions": {
                        "credId": f"{cred_id}",
                        "address": f"EVM:{self.client.account.address}",
                        "twitter": {"campaignID": f"{campaign_id}", "captcha": captcha},
                    },
                },
            },
            "query": "mutation SyncCredentialValue($input: SyncCredentialValueInput!) {\n  syncCredentialValue(input: $input) {\n    value {\n      address\n      spaceUsers {\n        follow\n        points\n        participations\n        __typename\n      }\n      campaignReferral {\n        count\n        __typename\n      }\n      galxePassport {\n        eligible\n        lastSelfieTimestamp\n        __typename\n      }\n      spacePoint {\n        points\n        __typename\n      }\n      spaceParticipation {\n        participations\n        __typename\n      }\n      gitcoinPassport {\n        score\n        lastScoreTimestamp\n        __typename\n      }\n      walletBalance {\n        balance\n        __typename\n      }\n      multiDimension {\n        value\n        __typename\n      }\n      allow\n      survey {\n        answers\n        __typename\n      }\n      quiz {\n        allow\n        correct\n        __typename\n      }\n      prediction {\n        isCorrect\n        __typename\n      }\n      spaceFollower {\n        follow\n        __typename\n      }\n      __typename\n    }\n    message\n    __typename\n  }\n}",
        }
        data = await self.request(json_data=json_data)
        return data["data"]["syncCredentialValue"]["value"]["allow"]

    async def sync_quest(self, cred_id: str):
        if not self.bearer_token:
            await self.auth()

        json_data = {
            "operationName": "SyncCredentialValue",
            "variables": {
                "input": {
                    "syncOptions": {
                        "credId": f"{cred_id}",
                        "address": f"EVM:{self.client.account.address}",
                    },
                },
            },
            "query": "mutation SyncCredentialValue($input: SyncCredentialValueInput!) {\n  syncCredentialValue(input: $input) {\n    value {\n      address\n      spaceUsers {\n        follow\n        points\n        participations\n        __typename\n      }\n      campaignReferral {\n        count\n        __typename\n      }\n      galxePassport {\n        eligible\n        lastSelfieTimestamp\n        __typename\n      }\n      spacePoint {\n        points\n        __typename\n      }\n      spaceParticipation {\n        participations\n        __typename\n      }\n      gitcoinPassport {\n        score\n        lastScoreTimestamp\n        __typename\n      }\n      walletBalance {\n        balance\n        __typename\n      }\n      multiDimension {\n        value\n        __typename\n      }\n      allow\n      survey {\n        answers\n        __typename\n      }\n      quiz {\n        allow\n        correct\n        __typename\n      }\n      prediction {\n        isCorrect\n        __typename\n      }\n      spaceFollower {\n        follow\n        __typename\n      }\n      __typename\n    }\n    message\n    __typename\n  }\n}",
        }
        data = await self.request(json_data=json_data)
        return data["data"]["syncCredentialValue"]["value"]["allow"]

    async def get_quest_cred_list(self, campaign_id: str):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            "operationName": "QuestCredList",
            "variables": {
                "id": campaign_id,
                "address": self.client.account.address,
            },
            "query": "query QuestCredList($id: ID!, $address: String!) {\n  campaign(id: $id) {\n    id\n    endTime\n    space {\n      alias\n      id\n      name\n      thumbnail\n      __typename\n    }\n    recurringType\n    latestRecurringTime\n    taskConfig(address: $address) {\n      participateCondition {\n        conditions {\n          ...ExpressionEntity\n          __typename\n        }\n        conditionalFormula\n        eligible\n        __typename\n      }\n      rewardConfigs {\n        id\n        conditions {\n          ...ExpressionEntity\n          __typename\n        }\n        conditionalFormula\n        description\n        rewards {\n          ...ExpressionReward\n          __typename\n        }\n        eligible\n        rewardAttrVals {\n          attrName\n          attrTitle\n          attrVal\n          __typename\n        }\n        __typename\n      }\n      referralConfig {\n        id\n        conditions {\n          ...ExpressionEntity\n          __typename\n        }\n        conditionalFormula\n        description\n        rewards {\n          ...ExpressionReward\n          __typename\n        }\n        eligible\n        rewardAttrVals {\n          attrName\n          attrTitle\n          attrVal\n          __typename\n        }\n        __typename\n      }\n      __typename\n    }\n    referralCode(address: $address)\n    __typename\n  }\n}\n\nfragment ExpressionReward on ExprReward {\n  arithmetics {\n    ...ExpressionEntity\n    __typename\n  }\n  arithmeticFormula\n  rewardType\n  rewardCount\n  rewardVal\n  __typename\n}\n\nfragment ExpressionEntity on ExprEntity {\n  cred {\n    id\n    name\n    credType\n    credSource\n    dimensionConfig\n    referenceLink\n    description\n    lastUpdate\n    lastSync\n    chain\n    curatorSpace {\n      id\n      name\n      thumbnail\n      __typename\n    }\n    eligible(address: $address)\n    metadata {\n      twitter {\n        isAuthentic\n        __typename\n      }\n      worldcoin {\n        dimensions {\n          values {\n            value\n            __typename\n          }\n          __typename\n        }\n        __typename\n      }\n      discord {\n        discordAma {\n          LinkIsInvalid\n          __typename\n        }\n        discordMember {\n          LinkIsInvalid\n          __typename\n        }\n        discordMessage {\n          LinkIsInvalid\n          __typename\n        }\n        __typename\n      }\n      prediction {\n        options {\n          option\n          isCorrect\n          chosenCount\n          __typename\n        }\n        deadlineForVoting\n        deadlineForReveal\n        rule\n        __typename\n      }\n      __typename\n    }\n    commonInfo {\n      participateEndTime\n      modificationInfo\n      __typename\n    }\n    __typename\n  }\n  attrs {\n    attrName\n    operatorSymbol\n    targetValue\n    __typename\n  }\n  attrFormula\n  eligible\n  eligibleAddress\n  __typename\n}",
        }
        return await self.request(json_data=json_data)

    async def prepare_participate(self, campaign_id: str, chain: str, capthca: dict, mint_count: int, point_mint_amount: int):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            "operationName": "PrepareParticipate",
            "variables": {
                "input": {
                    "signature": "",
                    "campaignID": campaign_id,
                    "address": f"EVM:{self.client.account.address}",
                    "mintCount": mint_count,
                    "chain": chain,
                    "claimVersion": "CHARGE_CLAIM_FEE_VERSION",
                    "pointMintAmount": point_mint_amount,
                    "captcha": capthca,
                },
            },
            "query": "mutation PrepareParticipate($input: PrepareParticipateInput!) {\n  prepareParticipate(input: $input) {\n    allow\n    disallowReason\n    signature\n    nonce\n    spaceStationInfo {\n      address\n      chain\n      version\n      __typename\n    }\n    mintFuncInfo {\n      funcName\n      nftCoreAddress\n      verifyIDs\n      powahs\n      cap\n      claimFeeAmount\n      __typename\n    }\n    extLinkResp {\n      success\n      data\n      error\n      __typename\n    }\n    metaTxResp {\n      metaSig2\n      autoTaskUrl\n      metaSpaceAddr\n      forwarderAddr\n      metaTxHash\n      reqQueueing\n      __typename\n    }\n    solanaTxResp {\n      mint\n      updateAuthority\n      explorerUrl\n      signedTx\n      verifyID\n      __typename\n    }\n    aptosTxResp {\n      signatureExpiredAt\n      tokenName\n      __typename\n    }\n    spaceStation\n    airdropRewardCampaignTxResp {\n      airdropID\n      verifyID\n      index\n      account\n      amount\n      proof\n      customReward\n      __typename\n    }\n    tokenRewardCampaignTxResp {\n      signatureExpiredAt\n      verifyID\n      encodeAddress\n      weight\n      claimFeeAmount\n      __typename\n    }\n    loyaltyPointsTxResp {\n      TotalClaimedPoints\n      VerifyIDs\n      loyaltyPointDistributionStation\n      signature\n      disallowReason\n      nonce\n      allow\n      loyaltyPointContract\n      Points\n      reqQueueing\n      claimFeeAmount\n      suiTxResp {\n        galxeTableId\n        __typename\n      }\n      __typename\n    }\n    flowTxResp {\n      Name\n      Description\n      Thumbnail\n      __typename\n    }\n    xrplLinks\n    suiTxResp {\n      packageId\n      tableId\n      nftName\n      campaignId\n      verifyID\n      imgUrl\n      signatureExpiredAt\n      __typename\n    }\n    algorandTxResp {\n      algorandArgs {\n        args\n        __typename\n      }\n      algorandBoxes {\n        boxes\n        __typename\n      }\n      __typename\n    }\n    spaceStationProxyResp {\n      target\n      callData\n      __typename\n    }\n    luckBasedTokenCampaignTxResp {\n      cid\n      dummyId\n      expiredAt\n      claimTo\n      index\n      claimAmount\n      proof\n      claimFeeAmount\n      signature\n      encodeAddress\n      weight\n      __typename\n    }\n    __typename\n  }\n}",
        }

        return await self.request(json_data=json_data)

    def _get_claim_params(self, campaign):
        wl_info = campaign["whitelistInfo"]
        point_mint_amount = wl_info["currentPeriodMaxLoyaltyPoints"] - wl_info["currentPeriodClaimedLoyaltyPoints"]
        mint_amount = 0 if wl_info["maxCount"] == -1 else wl_info["maxCount"] - wl_info["usedCount"]
        chain = "GRAVITY_ALPHA" if point_mint_amount > 0 else campaign["chain"]
        if point_mint_amount <= 0 and mint_amount <= 0:
            logger.debug(f"{self.wallet} nothing to claim")
            return False
        mint_log = []
        mint_log = " and ".join(mint_log)
        return {
            "pointMintAmount": point_mint_amount,
            "mintCount": mint_amount,
            "chain": chain,
        }

    async def get_campaign_info(self, campaign_id):
        json_data = {
            "operationName": "QuestClaimSection",
            "variables": {
                "isParent": False,
                "id": f"{campaign_id}",
                "address": f"{self.client.account.address}",
                "withAddress": True,
            },
            "query": "query QuestClaimSection($id: ID!, $address: String!, $withAddress: Boolean!, $isParent: Boolean = false) {\n  campaign(id: $id) {\n    ...QuestClaimFragment\n    boost(address: $address) {\n      golden\n      boost\n      boostedGold\n      reason\n      __typename\n    }\n    numNFTMinted\n    participants @skip(if: $isParent) {\n      participantsCount\n      __typename\n    }\n    userParticipants(address: $address, first: 1) @include(if: $withAddress) {\n      list {\n        status\n        __typename\n      }\n      __typename\n    }\n    name\n    description\n    userAgreement\n    airdrop {\n      rewardType\n      rewardAmount\n      rewardInfo {\n        custom {\n          name\n          icon\n          __typename\n        }\n        token {\n          address\n          decimals\n          symbol\n          icon\n          __typename\n        }\n        __typename\n      }\n      claimDetail(address: $address) {\n        amount\n        __typename\n      }\n      __typename\n    }\n    space {\n      isFollowing @include(if: $withAddress)\n      isVerified\n      __typename\n    }\n    inWatchList\n    __typename\n  }\n}\n\nfragment ExpressionReward on ExprReward {\n  arithmetics {\n    ...ExpressionEntity\n    __typename\n  }\n  arithmeticFormula\n  rewardType\n  rewardCount\n  rewardVal\n  __typename\n}\n\nfragment QuestClaimFragment on Campaign {\n  id\n  numberID\n  type\n  chain\n  status\n  distributionType\n  startTime\n  endTime\n  claimEndTime\n  cap\n  recurringType\n  loyaltyPoints\n  rewardName\n  rewardType\n  gasType\n  ...CampaignForGetImage\n  ...CampaignForTokenObject\n  space {\n    id\n    alias\n    discordGuildID\n    name\n    thumbnail\n    loyaltyPointContractList {\n      address\n      chain\n      status\n      __typename\n    }\n    __typename\n  }\n  ...WhitelistInfoFrag\n  ...WhitelistSubgraphFrag\n  rewardInfo {\n    discordRole {\n      roleName\n      guildName\n      inviteLink\n      __typename\n    }\n    gasConfig {\n      rewardEntity\n      gasType\n      __typename\n    }\n    __typename\n  }\n  nftHolderSnapshot {\n    holderSnapshotBlock\n    __typename\n  }\n  credentialGroups(address: $address) {\n    id\n    rewards {\n      rewardType\n      rewardCount\n      __typename\n    }\n    __typename\n  }\n  tokenReward {\n    raffleContractAddress\n    __typename\n  }\n  spaceStation {\n    address\n    __typename\n  }\n  parentCampaign {\n    id\n    __typename\n  }\n  taskConfig(address: $address) {\n    rewardConfigs {\n      id\n      conditions {\n        ...ExpressionEntity\n        __typename\n      }\n      conditionalFormula\n      description\n      rewards {\n        ...ExpressionReward\n        __typename\n      }\n      eligible\n      rewardAttrVals {\n        attrName\n        attrTitle\n        attrVal\n        __typename\n      }\n      __typename\n    }\n    requiredInfo {\n      socialInfos {\n        email\n        discordUserID\n        twitterUserID\n        telegramUserID\n        githubUserID\n        googleUserID\n        worldcoinID\n        __typename\n      }\n      addressInfos {\n        ...AddressInfosFrag\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n  nftTemplates {\n    id\n    animationURL\n    category\n    image\n    name\n    treasureBack\n    __typename\n  }\n  nftCore {\n    id\n    contractAddress\n    chain\n    transferable\n    createdAt\n    __typename\n  }\n  tokenReward {\n    userTokenAmount\n    tokenAddress\n    depositedTokenAmount\n    tokenRewardContract\n    tokenDecimal\n    tokenLogo\n    tokenSymbol\n    raffleContractAddress\n    suiTableId\n    suiCampaignId\n    __typename\n  }\n  __typename\n}\n\nfragment WhitelistInfoFrag on Campaign {\n  id\n  whitelistInfo(address: $address) {\n    address\n    maxCount\n    usedCount\n    claimedLoyaltyPoints\n    currentPeriodClaimedLoyaltyPoints\n    currentPeriodMaxLoyaltyPoints\n    xrplLinks\n    __typename\n  }\n  __typename\n}\n\nfragment WhitelistSubgraphFrag on Campaign {\n  id\n  whitelistSubgraph {\n    query\n    endpoint\n    expression\n    variable\n    __typename\n  }\n  __typename\n}\n\nfragment CampaignForGetImage on Campaign {\n  ...GetImageCommon\n  nftTemplates {\n    image\n    __typename\n  }\n  __typename\n}\n\nfragment GetImageCommon on Campaign {\n  ...CampaignForTokenObject\n  id\n  type\n  thumbnail\n  __typename\n}\n\nfragment CampaignForTokenObject on Campaign {\n  type\n  chain\n  cap\n  rewardInfo {\n    luckBasedToken {\n      totalAmount\n      userAvailableMaxAmount\n      tokenAddress\n      tokenDecimal\n      tokenLogo\n      tokenSymbol\n      withdrawnTokenAmount\n      hasDeposited\n      raffleContractAddress\n      luckBasedTokenRewardContract\n      __typename\n    }\n    __typename\n  }\n  tokenReward {\n    tokenAddress\n    tokenSymbol\n    tokenDecimal\n    tokenLogo\n    userTokenAmount\n    __typename\n  }\n  tokenRewardContract {\n    id\n    chain\n    address\n    __typename\n  }\n  __typename\n}\n\nfragment ExpressionEntity on ExprEntity {\n  cred {\n    id\n    name\n    credType\n    credSource\n    dimensionConfig\n    referenceLink\n    description\n    lastUpdate\n    lastSync\n    chain\n    curatorSpace {\n      id\n      name\n      thumbnail\n      __typename\n    }\n    eligible(address: $address)\n    metadata {\n      twitter {\n        isAuthentic\n        __typename\n      }\n      worldcoin {\n        dimensions {\n          values {\n            value\n            __typename\n          }\n          __typename\n        }\n        __typename\n      }\n      discord {\n        discordAma {\n          LinkIsInvalid\n          __typename\n        }\n        discordMember {\n          LinkIsInvalid\n          __typename\n        }\n        discordMessage {\n          LinkIsInvalid\n          __typename\n        }\n        __typename\n      }\n      prediction {\n        options {\n          option\n          isCorrect\n          chosenCount\n          __typename\n        }\n        deadlineForVoting\n        deadlineForReveal\n        rule\n        __typename\n      }\n      __typename\n    }\n    commonInfo {\n      participateEndTime\n      modificationInfo\n      __typename\n    }\n    __typename\n  }\n  attrs {\n    attrName\n    operatorSymbol\n    targetValue\n    __typename\n  }\n  attrFormula\n  eligible\n  eligibleAddress\n  __typename\n}\n\nfragment AddressInfosFrag on AddressInfos {\n  address\n  evmAddressSecondary\n  solanaAddress\n  aptosAddress\n  seiAddress\n  injectiveAddress\n  flowAddress\n  starknetAddress\n  suiAddress\n  bitcoinAddress\n  stacksAddress\n  azeroAddress\n  archwayAddress\n  xrplAddress\n  bitcoinSignetAddress\n  tonAddress\n  algorandAddress\n  kadenaAddress\n  __typename\n}",
        }
        return await self.request(json_data=json_data)

    async def get_smart_saving_balance(self) -> float:
        if not self.bearer_token:
            await self.auth()
        json_data = {
            'operationName': 'GetBalance',
            'variables': {
                'address': f'{self.wallet.address}',
            },
            'query': 'query GetBalance($address: String!) {\n  GetBalance(address: $address) {\n    token\n    balance\n    pendingAmount\n    __typename\n  }\n}',
        }
        data = await self.request(json_data=json_data, use_save=True)
        if not data['data']['GetBalance']:
            return 0.0
        return data['data']['GetBalance']


    async def handle_subscribe(self):
        if not self.bearer_token:
            await self.auth()
        if await self.get_subscription():
            return True
        client, token, amount = await self.choose_client_for_subscription()
        if not client or not token or not amount:
            logger.warning(f"{self.wallet} can't choose client for subscription")
            return False
        json_data = {
            'operationName': 'RegisterInstantPaymentTask',
            'variables': {
                'input': {
                    'taskParams': {
                        'amount': f'{amount.Wei}',
                        'token': f'{token}',
                        'chain': f'{client.network.name.upper()}',
                    },
                    'taskDetail': {
                        'plusTask': {
                            'paymentCycle': 'Monthly',
                            'planType': 'Mini',
                        },
                    },
                    'depositType': 'CrossChainSwapDeposit',
                    'permit': {
                        'deadline': 0,
                        'v': 0,
                        'r': '0x0000000000000000000000000000000000000000000000000000000000000000',
                        's': '0x0000000000000000000000000000000000000000000000000000000000000000',
                    },
                },
            },
            'query': 'mutation RegisterInstantPaymentTask($input: RegisterInstantPaymentTaskInput!) {\n  registerInstantPaymentTask(input: $input) {\n    taskId\n    taskFee\n    signature\n    ssEncodedData\n    ssVaultDepositSignature\n    depositToken\n    depositAmount\n    depositResponse {\n      messageFee\n      __typename\n    }\n    swapDepositResponse {\n      depositPool\n      messageFee\n      sourceSwap {\n        minOut\n        feeTier\n        __typename\n      }\n      sourceSwapPath\n      __typename\n    }\n    crossChainSwapDepositResponse {\n      targetEndpointId\n      targetToken\n      sourceSwap {\n        minOut\n        feeTier\n        __typename\n      }\n      targetSwap {\n        minOut\n        feeTier\n        __typename\n      }\n      nativeDrop\n      messageFee\n      sourceSwapPath\n      targetSwapPath\n      __typename\n    }\n    contractAddress\n    tokenTransfers {\n      amount\n      treasurer\n      __typename\n    }\n    __typename\n  }\n}',
        }
        logger.debug(json_data)
        data = await self.request(json_data=json_data)
        if 'registerInstantPaymentTask' not in data['data']:
            logger.warning(f"{self.wallet} can't get transactions details for subscribe data: {data}")
            return False
        return await self.galxe_onchain.subscription(client=Base(client=client, wallet=self.wallet), data=data)

    async def get_subscription(self):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            'operationName': 'GetUserPlusSubscription',
            'variables': {},
            'query': 'query GetUserPlusSubscription {\n  userPlusSubscription {\n    active\n    currentPlanType\n    currentPaymentCycle\n    expiresAt\n    beginsAt\n    __typename\n  }\n}',
        }
        data = await self.request(json_data=json_data)
        return data['data']['userPlusSubscription']['active']

    async def check_available_legend_box(self):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            'operationName': 'MysteryBoxes',
            'variables': {
                'address': f'EVM:{self.client.account.address}',
            },
            'query': 'query MysteryBoxes($address: String!) {\n  mysteryBoxes {\n    id\n    name\n    logo\n    available\n    participateFee {\n      id\n      chain\n      tokenAmount\n      tokenDetail {\n        ...TokenDetailFrag\n        __typename\n      }\n      __typename\n    }\n    discountParticipateFee {\n      id\n      chain\n      tokenAmount\n      tokenDetail {\n        ...TokenDetailFrag\n        __typename\n      }\n      __typename\n    }\n    rewardConfig {\n      rewardCount\n      rewardType\n      rewardCap\n      rewardDesc\n      rewardIndex\n      tokenDetail {\n        ...TokenDetailFrag\n        __typename\n      }\n      __typename\n    }\n    credentialGroups(address: $address) {\n      id\n      name\n      credentials {\n        id\n        name\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment TokenDetailFrag on TokenDetail {\n  id\n  chain\n  tokenDecimal\n  tokenLogo\n  tokenSymbol\n  tokenAddress\n  __typename\n}',
        }
        data = await self.request(json_data=json_data)
        return data['data']['mysteryBoxes'][-1]['available']
    
    async def open_box(self):
        if not self.bearer_token:
            await self.auth()
        captcha = await self.get_captcha('AddTypedCredentialItems')
        captcha.update({'encryptedData': ''})
        json_data = {
            'operationName': 'OpenMysteryBox',
            'variables': {
                'input': {
                    'id': '1003',
                    'count': 1,
                    'captcha': captcha,
                },
            },
            'query': 'mutation OpenMysteryBox($input: OpenMysteryBoxInput!) {\n  openMysteryBox(input: $input) {\n    description\n    rewards {\n      rewardCount\n      rewardIndex\n      rewardId\n      tokenDetail {\n        ...TokenDetailFrag\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment TokenDetailFrag on TokenDetail {\n  id\n  chain\n  tokenDecimal\n  tokenLogo\n  tokenSymbol\n  tokenAddress\n  __typename\n}',
        }
        data = await self.request(json_data=json_data)
        return data['data']['openMysteryBox']['rewards'][0]
    
    async def check_rewards(self):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            'operationName': 'UserTokenList',
            'variables': {
                'request': {
                    'afterId': 0,
                    'limit': 10,
                },
            },
            'query': 'query UserTokenList($request: ListUserTokensRequest!) {\n  listUserTokens(request: $request) {\n    totalCount\n    pageInfo {\n      startCursor\n      endCursor\n      hasNextPage\n      hasPreviousPage\n      __typename\n    }\n    list {\n      id\n      chain\n      tokenAmount\n      tokenDetail {\n        ...TokenDetailFrag\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment TokenDetailFrag on TokenDetail {\n  id\n  chain\n  tokenDecimal\n  tokenLogo\n  tokenSymbol\n  tokenAddress\n  __typename\n}',
        }
        return await self.request(json_data=json_data)
        
    async def check_fee_withdraw_reward(self, token_id: int, token_amount):
        if not self.bearer_token:
            await self.auth()
        json_data = {
            'operationName': 'RedeemTokenEstimation',
            'variables': {
                'input': {
                    'tokenId': token_id,
                    'tokenAmount': str(token_amount),
                },
            },
            'query': 'query RedeemTokenEstimation($input: RedeemTokenEstimationRequest!) {\n  redeemTokenEstimation(request: $input) {\n    gasFeeUSD\n    gasTokens {\n      paymentToken {\n        tokenAmount\n        tokenDetail {\n          ...TokenDetailFrag\n          __typename\n        }\n        __typename\n      }\n      paymentTokenAmount\n      gasTokenDetail {\n        ...TokenDetailFrag\n        __typename\n      }\n      gasTokenAmount\n      __typename\n    }\n    __typename\n  }\n}\n\nfragment TokenDetailFrag on TokenDetail {\n  id\n  chain\n  tokenDecimal\n  tokenLogo\n  tokenSymbol\n  tokenAddress\n  __typename\n}',
        }

        return await self.request(json_data=json_data, suffix="__galxe_web")

    async def redeem_tokens_rewards(self, token_id: int, token_amount):
        time_for_request = int(time.time())
        json_data = {
            'operationName': 'redeemToken',
            'variables': {
                'input': {
                    'tokenAmount': token_amount,
                    'redeemAddress': f'{self.wallet.address}',
                    'tokenId': token_id,
                    'timestamp': time_for_request,
                },
            },
            'query': 'mutation redeemToken($input: RedeemTokenRequest!) {\n  redeemToken(request: $input) {\n    success\n    __typename\n  }\n}',
        }
        return await self.request(json_data=json_data, suffix=f"__galxe_web_{time_for_request}")
