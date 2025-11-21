USE Trivia;
GO

CREATE OR ALTER PROCEDURE add_player
    @username NVARCHAR(50),
    @password_hash NVARCHAR(255),
    @user_email NVARCHAR(255) = NULL,
    @is_admin BIT = 0
AS
BEGIN
    SET NOCOUNT ON;

    -- Prevent duplicate usernames
    IF EXISTS (SELECT 1 FROM players WHERE username = @username)
    BEGIN
        PRINT 'Username already exists.';
        RETURN;
    END

    INSERT INTO players (username, password_hash, email, is_admin)
    VALUES (@username, @password_hash, @user_email, @is_admin);

    PRINT 'Player added successfully.';
END;
GO
