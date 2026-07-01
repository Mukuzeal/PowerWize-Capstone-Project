// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * EnergyWize Soulbound Certificate NFT (ERC-721)
 * - One token per certificate, non-transferable (soulbound)
 * - Metadata stored on-chain as base64-encoded JSON (no IPFS needed)
 * - Only contract owner (system wallet) can mint
 */
contract EnergyWizeCertificate is ERC721, Ownable {
    uint256 private _nextTokenId;
    mapping(uint256 => string) private _uris;

    constructor(address initialOwner)
        ERC721("EnergyWize Certificate", "EWCERT")
        Ownable(initialOwner)
    {}

    function mint(address to, string calldata uri) external onlyOwner returns (uint256) {
        uint256 tokenId = ++_nextTokenId;
        _safeMint(to, tokenId);
        _uris[tokenId] = uri;
        return tokenId;
    }

    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        _requireOwned(tokenId);
        return _uris[tokenId];
    }

    // Soulbound: block all transfers and burns — only minting (from == address(0)) is allowed
    function _update(address to, uint256 tokenId, address auth) internal override returns (address) {
        require(_ownerOf(tokenId) == address(0), "Soulbound: non-transferable");
        return super._update(to, tokenId, auth);
    }
}
