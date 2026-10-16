// Aus cs-demo-downloader (github.com/claabs/cs-demo-downloader, MIT-Lizenz, Commit 5281bff),
// kompiliert aus src/steam-gc.ts, mit einer Korrektur von cstaktik (siehe 'cstaktik-Patch').
import GlobalOffensive from 'globaloffensive';
import PQueue from 'p-queue';
import { decodeMatchShareCode } from 'csgo-sharecode';
import promiseTimeout from 'p-timeout';
import { config } from './config.js';
import logger from './logger.js';
import { loginSteamClient } from './steam.js';
import { getAllNewMatchCodes } from './match-history.js';
import { getStoreValue, setStoreValue } from './store.js';
import { downloadSaveDemo } from './download.js';
import { appendDemoLog } from './demo-log.js';
export const getUserShareCodes = async (user, shareCodesQueue) => {
    const { steamId64, authCode } = user;
    const L = logger.child({ steamId: steamId64 });
    try {
        const storeShareCode = await getStoreValue('lastShareCode', steamId64);
        const lastShareCode = storeShareCode ?? user.oldestShareCode;
        if (!lastShareCode)
            throw new Error('No share code found');
        L.debug({ lastShareCode }, 'Getting new share codes');
        const shareCodes = await getAllNewMatchCodes(steamId64, authCode, lastShareCode, shareCodesQueue);
        if (!storeShareCode) {
            shareCodes.unshift(lastShareCode);
        }
        return shareCodes.map((shareCode) => {
            const { matchId } = decodeMatchShareCode(shareCode);
            return { shareCode, steamId: steamId64, matchId };
        });
    }
    catch (err) {
        L.error({ err });
        return [];
    }
};
export const getAllUsersMatches = async (users, downloadQueue) => {
    if (!config.authCodeLogin)
        throw new Error('Missing auth code login credentials');
    const L = logger.child({ username: config.authCodeLogin.username });
    const shareCodesQueue = new PQueue({ concurrency: 1, interval: 1500, intervalCap: 1 });
    const usersShareCodeIds = await Promise.all(users.map(async (user) => getUserShareCodes(user, shareCodesQueue)));
    const shareCodes = Array.from(new Set(usersShareCodeIds.flat().map((id) => id.shareCode)));
    // Do nothing if no codes
    if (!shareCodes.length) {
        L.info('No new matches to download');
        return;
    }
    const steamUser = await loginSteamClient(config.authCodeLogin);
    steamUser.on('error', (err) => {
        L.error(err);
    });
    const waitForGame = promiseTimeout(new Promise((resolve) => {
        steamUser.once('appLaunched', (id) => {
            if (id === 730) {
                resolve();
            }
        });
    }), { milliseconds: 30000, message: 'Timed out waiting for game to launch' });
    // cstaktik-Patch: GlobalOffensive vor dem Spielstart anlegen. Sonst verpasst es das 'appLaunched'-Ereignis,
    // meldet sich nie beim Game Coordinator an (kein Hello) und die Match-Anfragen laufen ins Leere (Timeout).
    const csgo = new GlobalOffensive(steamUser);
    const waitForGC = promiseTimeout(new Promise((resolve) => {
        csgo.once('connectedToGC', () => resolve());
    }), { milliseconds: 90000, message: 'Timed out waiting for game coordinator' });
    steamUser.gamesPlayed(730, true);
    await waitForGame;
    await waitForGC;
    // robust match response promise handler
    const pendingMatchResponses = new Map();
    csgo.on('matchList', (matches) => {
        L.trace({ matchesLength: matches.length }, 'Recieved matchList event');
        matches.forEach((match) => {
            const cb = pendingMatchResponses.get(match.matchid);
            if (cb) {
                L.debug({ matchId: match.matchid }, 'Resolving match request');
                pendingMatchResponses.delete(match.matchid);
                cb(match);
            }
        });
    });
    L.info({ shareCodes }, 'Requesting metadata from game coordinator');
    const requestGameQueue = new PQueue({ concurrency: 1 });
    const matchFetchResults = await Promise.all(shareCodes.map((shareCode) => requestGameQueue.add(async () => {
        try {
            const { matchId } = decodeMatchShareCode(shareCode);
            L.debug({ matchId, shareCode }, 'Requesting game data');
            const [match] = await Promise.all([
                promiseTimeout(new Promise((resolve) => {
                    pendingMatchResponses.set(matchId.toString(), resolve);
                }), {
                    milliseconds: 30000,
                    message: `Error fetching match data for match ${shareCode}`,
                }),
                csgo.requestGame(shareCode),
            ]);
            return match;
        }
        catch (err) {
            L.error({ err, shareCode });
            return undefined;
        }
    }, { throwOnTimeout: true })));
    const resolvedMatches = matchFetchResults.filter((match) => match !== undefined);
    // Quit CS
    const waitForQuit = promiseTimeout(new Promise((resolve) => {
        steamUser.once('appQuit', (id) => {
            if (id === 730) {
                resolve();
            }
        });
    }), { milliseconds: 30000, message: 'Timed out waiting for game to quit' });
    steamUser.gamesPlayed([], true);
    await waitForQuit;
    steamUser.logOff();
    L.info({ resolvedMatchesCount: resolvedMatches.length }, 'Downloading new matches');
    // Convert demo download metadata
    const dlMatches = resolvedMatches.map((match) => {
        const playerCount = match.roundstatsall[0]?.reservation.account_ids.filter((id) => id !== 0)
            .length;
        const isWingman = playerCount && playerCount <= 4;
        const isPremier = match.roundstatsall[0]?.b_switched_teams; // null for comp, true for premier
        let type;
        if (isWingman) {
            type = 'wingman';
        }
        else if (isPremier) {
            type = 'premier';
        }
        else {
            type = 'competitive';
        }
        return {
            matchId: BigInt(match.matchid),
            url: match.roundstatsall.at(-1)?.map,
            date: new Date(match.matchtime * 1000),
            type,
        };
    });
    // Download the demos
    await appendDemoLog(dlMatches);
    const downloadResults = await Promise.all(dlMatches.map((match) => downloadQueue.add(() => downloadSaveDemo(match), { throwOnTimeout: true })));
    const failedDownloads = downloadResults.filter((id) => id !== null).sort();
    // Use each user's MatchIdentifiers to set the last working shareCode in the store
    await Promise.all(usersShareCodeIds.map(async (userShareCodeIds) => {
        let lastWorkingIdentifier;
        userShareCodeIds.some((matchIdentifier) => {
            if (resolvedMatches.some((match) => match.matchid === matchIdentifier.matchId.toString()) &&
                !failedDownloads.includes(matchIdentifier.matchId)) {
                lastWorkingIdentifier = matchIdentifier;
                return false;
            }
            return true;
        }, undefined);
        if (lastWorkingIdentifier)
            await setStoreValue('lastShareCode', lastWorkingIdentifier.steamId, lastWorkingIdentifier.shareCode);
    }));
};
